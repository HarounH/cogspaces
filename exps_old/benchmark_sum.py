import numpy as np

import json
import os
from json import JSONDecodeError
from os.path import join

import pandas as pd

from cogspaces.pipeline import get_output_dir

output_dir = join(get_output_dir(), 'benchmark')


def summarize():
    # NIPS final
    # basedir_ids = [31]
    # basedirs = [join(get_output_dir(), 'multi_nested', str(_id), 'run') for _id in basedir_ids]
    # Current figure nips final
    # basedir_ids = [6, 9, 15, 23]
    # 12 unmasked
    # 25 hcp_new_big / hcp_new_big_single
    basedir_ids = [12, 25]
    basedirs = [join(get_output_dir(), 'benchmark', str(_id), 'run') for _id in basedir_ids]
    res_list = []
    for basedir in basedirs:
        for exp_dir in os.listdir(basedir):
            exp_dir = join(basedir, exp_dir)
            try:
                config = json.load(open(join(exp_dir, 'config.json'), 'r'))
                info = json.load(open(join(exp_dir, 'info.json'), 'r'))
            except (JSONDecodeError, FileNotFoundError):
                continue
            datasets = config['datasets']
            dataset = datasets[0]
            if len(datasets) > 1:
                helper_datasets = '__'.join(datasets[1:])
            else:
                helper_datasets = 'none'
            config['dataset'] = dataset
            config['helper_datasets'] = helper_datasets
            score = info.pop('score')
            res = dict(**config, **info)
            for key, value in score.items():
                res[key] = value
            res_list.append(res)
    res = pd.DataFrame(res_list)

    df_agg = res.groupby(by=['dataset', 'source', 'model', 'with_std',
                             'helper_datasets']).aggregate(['mean', 'std', 'count'])

    df_agg = df_agg.fillna(0)

    results = {}
    for dataset in ['archi', 'brainomics', 'camcan', 'la5c']:
        results[dataset] = df_agg.loc[dataset]['test_%s' % dataset]

    results = pd.concat(results, names=['dataset'])
    print(results)
    results.to_csv(join(output_dir, 'results.csv'))


def plot():
    import matplotlib as mpl
    mpl.use('pdf')
    from matplotlib import gridspec
    from matplotlib.cm import get_cmap
    import matplotlib.pyplot as plt

    df = pd.read_csv(join(output_dir, 'results.csv'),
                     index_col=list(range(5)))

    df = df.query("source == 'hcp_new_big' or source == 'unmasked'")

    fig = plt.figure(figsize=(5.5015, 1.5))
    # make outer gridspec
    outer = gridspec.GridSpec(1, 2, wspace=.12)
    # make nested gridspecs
    gs1 = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=outer[0],
                                           wspace=.03)
    gs2 = gridspec.GridSpecFromSubplotSpec(1, 2,
                                           subplot_spec=outer[1], wspace=.03)
    axes = []
    for i in range(2):
        axes.append(fig.add_subplot(gs1[i], zorder=100 if i == 0 else 0))
    for i in range(2):
        axes.append(fig.add_subplot(gs2[i]))

    fig.subplots_adjust(bottom=.1, left=.08, right=1, top=.8)

    limits = {'archi': [0.75, 0.95],
              'brainomics': [0.75, 0.95],
              'camcan': [0.5, 0.685],
              'la5c': [0.5, 0.685]}
    global_limits = [.52, .93]
    keys = [5, 4, 3, 2, 1, 0]
    labels = ['Full input + L2',
              'Dim. reduction + L2',
              'Dim. red. + dropout',
              '\\textbf{Factored model} + dropout',
              '\\textbf{Transfer} from HCP',
              '\\textbf{Transfer} from all datasets']
    names = {'archi': 'Archi',
             'brainomics': 'Brainomics',
             'camcan': 'CamCan',
             'la5c': 'LA5C',
             }

    colors = get_cmap('tab10').colors[:6]
    bars = []
    for ax, dataset in zip(axes, ['archi', 'brainomics', 'camcan', 'la5c']):
        dataset_df = df.loc[dataset]
        dataset_df.reset_index(['source', 'with_std'], drop=True,
                               inplace=True)
        data = dataset_df.iloc[keys]
        values = data['mean']
        stds = data['std']
        xs = np.linspace(.5, 5.5, 6)
        these_bars = ax.bar(xs, values, width=.8, color=colors, edgecolor=None,
                            linewidth=0,
                            label=[], alpha=.8)
        for bar, std in zip(these_bars, stds):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height + std,
                    '%2.1f' % (height * 100), fontsize=6.5,
                    ha='center', va='bottom')
        # Legend
        if dataset == 'archi':
            bars = these_bars
        errorbars = []
        for x, color, value, std in zip(xs, colors, values, stds):
            errorbar = ax.errorbar(x, value, yerr=std, elinewidth=1.2,
                                   capsize=2, linewidth=0, ecolor=color,
                                   alpha=.8)
            errorbars.append(errorbar)
        idx = np.argmax(values.values)

        # plt.setp(these_bars[idx], edgecolor='k', linewidth=1.5)
        x = these_bars[idx].get_x()
        wi = these_bars[idx].get_width()
        y = (these_bars[idx].get_height()
             - limits[dataset][0]) / (limits[dataset][1] - limits[dataset][0])
        ax.axvspan(x, x + wi, ymax=y, facecolor='none', edgecolor='black',
                   linewidth=1.5, zorder=100)

        ax.annotate(names[dataset],
                    xytext=(0, -3),
                    textcoords='offset points',
                    xy=(0.5, 0), va='top', ha='center', rotation=0,
                    xycoords='axes fraction')
        # sns.despine(fig, ax)
        ax.set_ylim(limits[dataset])
        ax.tick_params(axis='y', which='both', labelsize=6)
        if dataset in ['brainomics', 'la5c']:
            ax.set_yticks([])
            ax.spines['left'].set_visible(False)
        else:
            vals = ax.get_yticks()
            ax.set_yticklabels(['{:2.0f}\\%'.format(x * 100) for x in vals])
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.set_xticks([])

    axes[0].set_ylabel('Test accuracy')

    axes[0].legend(bars, labels, frameon=False, loc='lower left',
                   ncol=3,
                   bbox_to_anchor=(-.3, .93))
    fig.savefig(join(output_dir, 'ablation.pdf'))

# summarize()
plot()