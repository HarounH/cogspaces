import os
import sys
from os import path
from os.path import join

import numpy as np
from sacred import Experiment
from sacred.observers import FileStorageObserver
from sklearn.externals.joblib import Parallel
from sklearn.externals.joblib import delayed
from sklearn.utils import check_random_state

from cogspaces.pipeline import get_output_dir

# Add examples to known modules
sys.path.append(path.dirname(path.dirname
                             (path.dirname(path.abspath(__file__)))))
from exps.exp_predict import exp as single_exp

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
    datasets = ['archi', 'hcp']
    reduced_dir = join(get_output_dir(), 'reduced')
    unmask_dir = join(get_output_dir(), 'unmasked')
    source = 'hcp_rs_concat'
    n_subjects = None
    test_size = {'hcp': .1, 'archi': .5, 'brainomics': .5, 'camcan': .5,
                 'la5c': .5}
    train_size = {'hcp': .9, 'archi': .5, 'brainomics': .5, 'camcan': .5,
                  'la5c': .5}
    alpha = 0
    beta = 0
    model = 'trace'
    max_iter = 600
    verbose = 10
    with_std = False
    with_mean = False
    row_standardize = False


def single_run(config_updates, rundir, _id):
    run = single_exp._create_run(config_updates=config_updates)
    observer = FileStorageObserver.create(basedir=rundir)
    run._id = _id
    run.observers = [observer]
    try:
        run()
    except:
        pass


@exp.automain
def run(n_seeds, n_jobs, _run, _seed):
    seed_list = check_random_state(_seed).randint(np.iinfo(np.uint32).max,
                                                  size=n_seeds)
    exps = []
    for source in ['hcp_rs_positive_single']:
        for dataset in ['brainpedia']:
            log = [{'datasets': [dataset, 'hcp'],
                    'beta': beta,
                    'model': 'logistic',
                    'source': source,
                    'seed': seed} for seed in seed_list
                   for beta in [0] + np.logspace(-10, -1, 10).tolist()
                   ]
            transfer = [{'datasets': [dataset, 'hcp'],
                         'alpha': alpha,
                         'source': source,
                         'split_loss': split_loss,
                         'seed': seed} for seed in seed_list
                        for alpha in [0] + np.logspace(-6, 0, 13).tolist()
                        for split_loss in [True]
                        ]
            exps += log
            exps += transfer

    rundir = join(basedir, str(_run._id), 'run')
    if not os.path.exists(rundir):
        os.makedirs(rundir)

    Parallel(n_jobs=n_jobs,
             verbose=10)(delayed(single_run)(config_updates, rundir, i)
                         for i, config_updates in enumerate(exps))
