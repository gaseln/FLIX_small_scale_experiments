# Explicit Mixture of Local and Global models #

This repository contains the code to run small-scale experiments presented in the paper ["FLIX: A Simple and Communication-Efficient Alternative to Local Methods in Federated Learning"](https://arxiv.org/abs/2111.11556). For large-scale experiments, look at [add_link](google.com).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Installing environment and running Jupyter Lab ##

1. Install conda, _e.g._, following instructions on [this link](https://conda.io/projects/conda/en/latest/user-guide/install/index.html).
2. Run ```conda env create --prefix envs/ -f requirements/explicit_2.yml``` in the project directory.
3. Pip install tenforflow-federated nightly version with ```envs/bin/pip install --upgrade tensorflow-federated-nightly```.
4. Activate the environment ```conda activate envs/```.
5. Run ```jupyter lab``` to launch [Jupyter Lab](https://jupyter.org/).

## Downloading and preprocessing the datasets ##

1. Figure 1 datasets. Run all cells in 'Stackoverflow_simple_data_retriever.ipynb'.
2. Figure 2, 3 datasets. In datasets folder of the project download 
* **w6a** dataset ```wget https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary/w6a```,
* **ijcnn1.bz2** dataset ```wget https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary/ijcnn1.bz2```,
* **mushrooms** dataset ```wget https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary/mushrooms```,
* **a6a** dataset ```wget https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary/a6a```.
3. Figure 4 datasets. Run cells in 'Two_distribution_experiments.ipynb'.

## Figures and corresponding Python Notebooks. ##

1. The notebook of Figure 1 experiments is 'Stackoverflow_basic_Multiclass_Logistic_Regression.ipynb'. 
* To get the **first plot (Figure 1a)** in the section "Basic experimental setup" set ```exp_keyword = 'SO_LR_two_workers_100'``` and ```n_workers = 100```, and run all cells. 
* To get the **second plot (Figure 1b)** in the same section set ```exp_keyword = 'SO_LR_one_cluster_50'``` and ```n_workers = 50```.
2. The notebook for Figures 2 and 3 experiments is 'Experiments.ipynb'.
3. The notebook for Figure 4 is 'Two_distribution_experiments.ipynb'.
4. Notebook for convex experiments in the supplementary is 'Experiments_cvx.ipynb'.
