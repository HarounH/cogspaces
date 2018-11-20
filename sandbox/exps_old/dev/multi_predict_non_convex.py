import sys

import numpy as np
import os
from cogspaces.pipeline import get_output_dir
from os import path
from os.path import join
from sacred import Experiment
from sacred.observers import FileStorageObserver
from sklearn.externals.joblib import Parallel
from sklearn.externals.joblib import delayed
from sklearn.utils import check_random_state

# Add examples to known models
sys.path.append(path.dirname(path.dirname
                             (path.dirname(path.abspath(__file__)))))
from exps_old.old.exp_predict import exp as single_exp

exp = Experiment('predict_multi')
basedir = join(get_output_dir(), 'predict_multi')
if not os.path.exists(basedir):
    os.makedirs(basedir)
exp.observers.append(FileStorageObserver.create(basedir=basedir))


@exp.config
def config():
    n_jobs = 24
    n_seeds = 20
    seed = 2


@single_exp.config
def config():
    datasets = ['archi', 'hcp', 'brainomics']
    reduced_dir = join(get_output_dir(), 'reduced')
    unmask_dir = join(get_output_dir(), 'unmasked')
    source = 'hcp_rs_positive_single'
    test_size = {'hcp': .1, 'archi': .5, 'brainomics': .5, 'camcan': .5,
                 'la5c': .5, 'full': .5}
    train_size = dict(hcp=None, archi=None, la5c=None, brainomics=None,
                      camcan=None,
                      human_voice=None)
    dataset_weights = {'brainomics': 1, 'archi': 1, 'hcp': 1}
    model = ''
    alpha = 7e-4
    max_iter = 100
    verbose = 10
    seed = 10

    with_std = False
    with_mean = False
    per_dataset = False
    split_loss = True

    # Factored only
    n_components = 'auto'
    latent_dropout_rate = 0.
    input_dropout_rate = 0.
    batch_size = 128
    optimizer = 'lbfgs'
    step_size = 1


def single_run(config_updates, rundir, _id):
    run = single_exp._create_run(config_updates=config_updates)
    observer = FileStorageObserver.create(basedir=rundir)
    run._id = _id
    run.observers = [observer]
    run()


@exp.automain
def run(n_seeds, n_jobs, _run, _seed):
    seed_list = check_random_state(_seed).randint(np.iinfo(np.uint32).max,
                                                  size=n_seeds)
    exps = []
    for seed in seed_list:
        for alpha in np.logspace(-7, 0, 15):
            for model in ['logistic', 'trace', 'factored']:
                exps.append({'alpha': alpha,
                             'model': model,
                             'max_iter': 2000 if model == 'trace' else 100,
                             'seed': seed})
    np.random.shuffle(exps)

    rundir = join(basedir, str(_run._id), 'run')
    if not os.path.exists(rundir):
        os.makedirs(rundir)

    Parallel(n_jobs=n_jobs,
             verbose=10)(delayed(single_run)(config_updates, rundir, i)
                         for i, config_updates in enumerate(exps))