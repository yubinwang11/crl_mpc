"""
Curriculum RL with MPC for Autonomous Driving
"""

import numpy as np
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from functools import partial
import argparse
import copy

from pathlib import Path
import os

import torch
from torch import nn
from torch.cuda.amp.grad_scaler import GradScaler
from torch.cuda.amp.autocast_mode import autocast
import torch.optim as optim

import wandb

from learning_mpc.lane_change.env import Env
from learning_mpc.lane_change.animation import SimVisual
from networks import DNN
from worker import Worker_Train

from parameters import *

def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run_wandb', type=bool, default=True,
                        help="Monitor by wandb")
    parser.add_argument('--episode_num', type=float, default=500,
                        help="Number of episode")
    parser.add_argument('--save_model_window', type=float, default=32,
                        help="The time gap of saving a model")
    parser.add_argument('--save_model', type=bool, default=True,
                        help="Save the model of nn")
    parser.add_argument('--load_model', type=bool, default=False,
                        help="Load the trained model of nn")
    parser.add_argument('--use_SE3', type=bool, default=False,
                        help="Baselines")
    return parser

def main():

    args = arg_parser().parse_args()

    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

    num_episode = args.episode_num

    env_mode = 'hard'
    env = Env(curriculum_mode=env_mode, use_SE3=args.use_SE3)

    obs=env.reset()
    nn_input_dim = len(obs)
    use_gpu = False
    if torch.cuda.is_available():
        use_gpu = True
        
    if (args.use_SE3):
        nn_output_dim=4
    else:
        nn_output_dim = 13

    model = DNN(input_dim=nn_input_dim,
                                output_dim=nn_output_dim,
                                net_arch=NET_ARCH,model_togpu=use_gpu,device=device)

    optimizer = optim.Adam(model.high_policy.parameters(), lr=learning_rate)
    lr_decay = optim.lr_scheduler.StepLR(optimizer, step_size=DECAY_STEP, gamma=decay_gamma)

    if args.load_model:
        model_path = "./" + "models/augmented" + "CRL/"
        print('Loading Model...')
        if torch.cuda.is_available():
            checkpoint = torch.load(model_path + '/checkpoint.pth')
        else:
            checkpoint = torch.load(model_path + '/checkpoint.pth', map_location=torch.device('cpu'))
        model.load_state_dict(checkpoint['model'])
        optimizer.load_state_dict(checkpoint['optimizer'])
        lr_decay.load_state_dict(checkpoint['lr_decay'])
        curr_episode = checkpoint['episode']
        print("curr_episode set to ", curr_episode)

    if args.run_wandb:
        wandb.init(
        # set the wandb project where this run will be logged
        project="lane-change",
        entity="yubinwang",
        # track hyperparameters and run metadata
        config={
        #"learning_rate": learning_rate,
        "exp_decay": env.sigma,
        "init_lr": learning_rate,
        "nn_output_dim": nn_output_dim,
        }
    )

    for episode_i in range(num_episode):
        
        print("===========================================================")    
        print("episode is :", episode_i)

        if episode_i <= 100:
            env_mode = 'easy'
        
        elif 100 < episode_i <= 200:
            env_mode = 'medium'

        elif 200 < episode_i <= 500:
            env_mode = 'hard'
        
        env = Env(curriculum_mode=env_mode, use_SE3=args.use_SE3)
        obs=env.reset()

        worker = Worker_Train(env)
        worker_copy_list = [] 
        
        if torch.cuda.is_available():
            obs = torch.tensor(obs, dtype=torch.float32).to(device)
            model.to(device)
        else:
            obs = torch.tensor(obs, dtype=torch.float32)

        with autocast():
            high_variable = model.forward(obs)
        
            #scaler = GradScaler()
            z = high_variable

            mean = obs.mean(); std = obs.std()
            high_variable = high_variable*std + mean

            if torch.cuda.is_available():
                high_variable = high_variable.cpu().detach().numpy().tolist()
            else:
                high_variable = high_variable.detach().numpy().tolist()

            for i in range (len(high_variable)):
                worker_copy = copy.deepcopy(worker)
                worker_copy_list.append(worker_copy)

            ep_reward = worker.run_episode(high_variable, args)

            if torch.cuda.is_available():
                finite_diff_policy_grad = torch.tensor(np.zeros(len(high_variable)), dtype=torch.float32).to(device)
            else:
                finite_diff_policy_grad = torch.tensor(np.zeros(len(high_variable)), dtype=torch.float32)

            for k in range(len(high_variable)):
                unit_k = np.zeros(len(high_variable))
                unit_k[k] = 1
                #noise_weight = np.random.rand()
                #noise = np.random.randn(len(pertubed_high_variable)) * noise_weight
                noise = np.random.randn() #* noise_weight # 1.5
                noise_vec = unit_k * noise
                pertubed_high_variable = high_variable + noise_vec
                pertubed_high_variable = pertubed_high_variable.tolist()

                pertubed_ep_reward_k = worker_copy_list[k].run_episode(pertubed_high_variable, args) #run_episode(env,goal)
                finite_diff_policy_grad_k = (pertubed_ep_reward_k - ep_reward)/noise
                finite_diff_policy_grad[k] = finite_diff_policy_grad_k
                
            loss = model.compute_loss(-finite_diff_policy_grad, z)

        optimizer.zero_grad()

        #torch.autograd.set_detect_anomaly(True)
        #with torch.autograd.detect_anomaly():
            #scaler.scale(loss).backward()
        loss.backward()

        #for param in model.high_policy.parameters():
            #print(param.grad)
            #if param.grad is not None and torch.isnan(param.grad).any():
                #print("nan gradient found")

        #scaler.unscale_(optimizer)
        #grad_norm = torch.nn.utils.clip_grad_norm_(model.high_policy.parameters(), max_norm=10, norm_type=2) # 0.5
        #torch.nn.utils.clip_grad_value_(model.high_policy.parameters(), 0.5)
        grad_norm = torch.nn.utils.clip_grad_norm_(model.high_policy.parameters(), max_norm=10, norm_type=2)

        optimizer.step()
        #scaler.step(optimizer)

        #scale = scaler.get_scale()
        #scaler.update()

        #skip_lr_sched = (scale > scaler.get_scale())
        #if not skip_lr_sched:
        lr_decay.step() #scheduler.step()
        #lr_decay.step()
        best_model = copy.deepcopy(model)

        if args.run_wandb:
            if not (args.use_SE3):
                wandb.log({"episode": episode_i, "reward": ep_reward, "loss": loss, "travese time": high_variable[-1], "position_x":high_variable[0], "position_y": high_variable[1], \
                        "heading": high_variable[2], "speed": high_variable[3],"vy": high_variable[4],"omega": high_variable[5],\
                        "Q_x":high_variable[6], "Q_y": high_variable[7], "Q_heading": high_variable[8], "Q_vx": high_variable[9],"Q_vy": high_variable[10],"Q_omega": high_variable[11],\
                            "grad_norm": grad_norm})
                #wandb.watch(model, log='all', log_freq=1)
            elif (args.use_SE3):
                wandb.log({"episode": episode_i, "reward": ep_reward, "loss": loss, "travese time": high_variable[-1], "position_x":high_variable[0], "position_y": high_variable[1], \
                        "heading": high_variable[2],  "grad_norm": grad_norm})
                #wandb.watch(model, log='all', log_freq=1)

        if args.save_model:

            if episode_i > 0 and episode_i % args.save_model_window == 0: ##default 100
                #print('Saving model', end='\n')
                if not (args.use_SE3):
                    model_path = "models/augmented/CRL"
                else:
                    model_path = "models/SE3/CRL"
                print('Saving model', end='\n')
                checkpoint = {"model": best_model.state_dict(),
                              "optimizer": optimizer.state_dict(),
                              "episode": episode_i,
                              "lr_decay": lr_decay.state_dict()}

                path_checkpoint = "./" + model_path + "/checkpoint.pth"
                torch.save(checkpoint, path_checkpoint)
                print('Saved model', end='\n')

    if args.run_wandb:
        wandb.finish()        
    
if __name__ == "__main__":
    main()