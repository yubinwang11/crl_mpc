import numpy as np
import casadi as ca
#from scipy.spatial.transform import Rotation as R
from common.vehicle_index import *
#
"""
Standard Vehicle Dynamics with Bicycle Model
"""
class Bicycle_Dynamics(object):
    #
    def __init__(self, dt):
        self.s_dim = 6
        self.a_dim = 2
        #
        self._state = np.zeros(shape=self.s_dim) 
        self._actions = np.zeros(shape=self.a_dim)

        #
        self._gz = 9.81
        self._dt = dt# self._arm_l = 0.3   # m
        
        ## Vehicle Parameter settings
        self.length = 3.5 # 4.5
        self.width =2 #

        self.kf = -128916
        self.kr = -85944
        self.lf = 1.06
        self.lr = 1.85
        self.m = 1412
        self.Iz = 1536.7
        self.Lk = (self.lf*self.kf) - (self.lr*self.kr)

        #
        #self.reset()
        # self._t = 0.0
    
    def reset(self, position=None, vx = None):
        self._state = np.zeros(shape=self.s_dim) 

        if position is None:
            # self._state[kQuatW] = 1.0 #         
            #
            # initialize position,  not randomly
            #self._state[kpx] = np.random.uniform(
                #low=self._xyz_dist[0, 0], high=self._xyz_dist[0, 1])
            
            self._state[kpx]  = 0    
            self._state[kpy] = 0 #np.random.uniform(
                #low=self._xyz_dist[1, 0], high=self._xyz_dist[1, 1])
            #self._state[kPosZ] = np.random.uniform(
                #low=self._xyz_dist[2, 0], high=self._xyz_dist[2, 1])
            
            # initialize heading
            #quad_quat0 = np.random.uniform(low=0.0, high=1, size=4)
            # normalize the quaternion
            #self._state[kQuatW:kQuatZ+1] = quad_quat0 / np.linalg.norm(quad_quat0)
            self._state[kphi] = 0
            
            # initialize velocity, not randomly
            #self._state[kVelX] = np.random.uniform(
                #low=self._vxyz_dist[0, 0], high=self._vxyz_dist[0, 1])
            self._state[kvx] = 0
            #self._state[kVelY] = np.random.uniform(
                #low=self._vxyz_dist[1, 0], high=self._vxyz_dist[1, 1])
            self._state[kvy] = 0
            self._state[komega] = 0
            #
        else:
            self._state[kpx] = position[0]
            self._state[kpy] = position[1]
            # heading
            self._state[kphi] = np.array([0])
            # v
            self._state[kvx] = vx
            self._state[kvy] = 0
            
            # initialize angular velocity
            self._state[komega] = 0
            #
        return self._state.tolist()
    
    def run(self, action):
        """
        Apply the control command on the vehicle and transits the system to the next state
        """
        # rk4 int
        M = 4
        DT = self._dt / M
        #
        X = self._state
        for i in range(M):
            k1 = DT*self._f(X, action)
            k2 = DT*self._f(X + 0.5*k1, action)
            k3 = DT*self._f(X + 0.5*k2, action)
            k4 = DT*self._f(X + k3, action)
            #
            X = X + (k1 + 2.0*(k2 + k3) + k4)/6.0
        #
        self._state = X
        #print(f"real state is {self._state}")
        return self._state.tolist()

    def _f(self, state, action):
        """
        System dynamics: ds = f(x, u)
        """
        px, py, phi, vx, vy, omega = state                    
        a, delta = action
        #
        dstate = np.zeros(shape=self.s_dim)

        dstate[kpx] = vx*np.cos(phi) - vy*np.sin(phi)
        dstate[kpy] = vy*np.cos(phi) + vx*np.sin(phi)
        dstate[kphi] = omega; dstate[kvx] = a
        dstate[kvy] = (self.Lk*omega - self.kf*delta*vx - self.m*(vx**2)*omega + vy*(self.kf+self.kr)) / (self.m*vx - self._dt*(self.kf+self.kr))
        dstate[komega] = (self.Lk*vy - self.lf*self.kf*delta*vx + omega*((self.lf**2)*self.kf + (self.lr**2)*self.kr)) / \
                                    (self.Iz*vx - self._dt*((self.lf**2)*self.kf + (self.lr**2)*self.kr))


        return dstate

    '''
    def set_state(self, state):
        """
        Set the vehicle's state
        """
        self._state = state
        
    def get_state(self):
        """
        Get the vehicle's state
        """
        return self._state

    def get_cartesian_state(self):
        """
        Get the Full state in Cartesian coordinates
        """
        cartesian_state = np.zeros(shape=9)
        cartesian_state[0:3] = self.get_position()
        cartesian_state[3:6] = self.get_euler()
        cartesian_state[6:9] = self.get_velocity()
        return cartesian_state
    
    def get_position(self,):
        """
        Retrieve Position
        """
        return self._state[kPosX:kPosZ+1]
    
    def get_velocity(self,):
        """
        Retrieve Linear Velocity
        """
        return self._state[kVelX:kVelZ+1]
    
    def get_quaternion(self,):
        """
        Retrieve Quaternion
        """
        quat = np.zeros(4)
        quat = self._state[kQuatW:kQuatZ+1]
        quat = quat / np.linalg.norm(quat)
        return quat

    def get_euler(self,):
        """
        Retrieve Euler Angles of the Vehicle
        """
        quat = self.get_quaternion()
        euler = self._quatToEuler(quat)
        return euler

    def get_axes(self):
        """
        Get the 3 axes (x, y, z) in world frame (for visualization only)
        """
        # axes in body frame
        b_x = np.array([self._arm_l, 0, 0])
        b_y = np.array([0, self._arm_l, 0])
        b_z = np.array([0, 0,  -self._arm_l])
        
        # rotation matrix
        rot_matrix = R.from_quat(self.get_quaternion()).as_matrix()
        quad_center = self.get_position()
        
        # axes in body frame
        w_x = rot_matrix@b_x + quad_center
        w_y = rot_matrix@b_y + quad_center
        w_z = rot_matrix@b_z + quad_center
        return [w_x, w_y, w_z]

    def get_motor_pos(self):
        """
        Get the 4 motor poses in world frame (for visualization only)
        """
        # motor position in body frame
        b_motor1 = np.array([np.sqrt(self._arm_l/2), np.sqrt(self._arm_l/2), 0])
        b_motor2 = np.array([-np.sqrt(self._arm_l/2), np.sqrt(self._arm_l/2), 0])
        b_motor3 = np.array([-np.sqrt(self._arm_l/2), -np.sqrt(self._arm_l/2), 0])
        b_motor4 = np.array([np.sqrt(self._arm_l/2), -np.sqrt(self._arm_l/2), 0])
        #
        rot_matrix = R.from_quat(self.get_quaternion()).as_matrix()
        quad_center = self.get_position()
        
        # motor position in world frame
        w_motor1 = rot_matrix@b_motor1 + quad_center
        w_motor2 = rot_matrix@b_motor2 + quad_center
        w_motor3 = rot_matrix@b_motor3 + quad_center
        w_motor4 = rot_matrix@b_motor4 + quad_center
        return [w_motor1, w_motor2, w_motor3, w_motor4]

    @staticmethod
    def _quatToEuler(quat):
        """
        Convert Quaternion to Euler Angles
        """
        quat_w, quat_x, quat_y, quat_z = quat[0], quat[1], quat[2], quat[3]
        euler_x = np.arctan2(2*quat_w*quat_x + 2*quat_y*quat_z, quat_w*quat_w - quat_x*quat_x - quat_y*quat_y + quat_z*quat_z)
        euler_y = -np.arcsin(2*quat_x*quat_z - 2*quat_w*quat_y)
        euler_z = np.arctan2(2*quat_w*quat_z+2*quat_x*quat_y, quat_w*quat_w + quat_x*quat_x - quat_y*quat_y - quat_z*quat_z)
        return [euler_x, euler_y, euler_z]
    
    '''