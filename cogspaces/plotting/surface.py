from os.path import join

import numpy as np
from mayavi import mlab
from nilearn import datasets, image, surface

fsaverage = datasets.fetch_surf_fsaverage5()


##############################################################################
# Helper functions
def save_views(fig, name, actors, distance=400, zoom=1,
               right_actors=None, left_actors=None,
               output_dir='.'):
    fig.scene.z_minus_view()
    mlab.view(distance=1.1 * distance)
    mlab.savefig(join(output_dir, '%s_bottom.png') % name,
                 size=(zoom * 896, zoom * 1024))

    fig.scene.z_plus_view()
    mlab.view(distance=1.06 * distance)
    mlab.savefig(join(output_dir, '%s_top.png') % name,
                 size=(zoom * 896, zoom * 1024))

    fig.scene.x_plus_view()
    mlab.view(distance=distance)
    mlab.savefig(join(output_dir, '%s_right.png') % name,
                 size=(zoom * 1024, zoom * 896))

    fig.scene.x_minus_view()
    mlab.view(distance=distance)
    mlab.savefig(join(output_dir, '%s_left.png') % name,
                 size=(zoom * 1024, zoom * 896))

    fig.scene.y_minus_view()
    mlab.view(roll=0, distance=.85 * distance)
    mlab.savefig(join(output_dir, '%s_back.png') % name,
                 size=(zoom * 1024, zoom * 896))

    # Side & front
    mlab.view(55, 73, .92 * distance)
    mlab.savefig(join(output_dir, '%s_oblique.png') % name,
                 size=(zoom * 1024, zoom * 896))

    if right_actors is not None and left_actors is not None:
        # Plot the medial views
        fig.scene.disable_render = True
        for actor in actors['right']:
            actor.actor.visible = False
        fig.scene.x_plus_view()
        mlab.view(distance=.96 * distance)
        fig.scene.disable_render = False
        mlab.savefig('%s_left_medial.png' % name,
                     size=(zoom * 1024, zoom * 896))
        fig.scene.disable_render = True
        for actor in actors['right']:
            actor.actor.visible = True

        for actor in actors['left']:
            actor.actor.visible = False
        fig.scene.x_minus_view()
        mlab.view(distance=.96 * distance)
        fig.scene.disable_render = False
        mlab.savefig('%s_right_medial.png' % name,
                     size=(zoom * 1024, zoom * 896))
        fig.scene.disable_render = True
        for actor in actors['left']:
            actor.actor.visible = True
        fig.scene.disable_render = False


def plot_on_surf(data, sides=['left', 'right'], selected=False,
                 threshold=None, inflate=1.001, **kwargs):
    """ Plot a numpy array of data on the corresponding fsaverage
        surface.

        The kwargs are passed to mlab.triangular_mesh
    """
    actors = dict()
    for side in sides:
        actors[side] = list()
        mesh = surface.load_surf_mesh(fsaverage['infl_%s' % side])
        shift = -42 if side == 'left' else 42
        surf = mlab.triangular_mesh(inflate * mesh[0][:, 0] + shift,
                                    inflate * mesh[0][:, 1],
                                    inflate * mesh[0][:, 2],
                                    mesh[1],
                                    scalars=data,
                                    **kwargs,
                                    )
        surf.module_manager.source.filter.splitting = False
        # Avoid openGL bugs with backfaces
        surf.actor.property.backface_culling = True
        actors[side].append(surf)

        if threshold is not None:
            surf.enable_contours = True
            surf.contour.auto_contours = False
            surf.contour.contours = [threshold, data.max()]
            surf.contour.filled_contours = True
            # A trick exploiting a bug in Z-ordering to highlight the
            # contour
            surf.actor.property.opacity = .5
            # Add a second surface to fill the contours
            if selected:
                dark_color = tuple(.3 * c for c in kwargs['color'])
            else:
                dark_color = tuple(.5 * c for c in kwargs['color'])
            surf2 = mlab.pipeline.contour_surface(surf, color=dark_color,
                                                  line_width=8 if selected else 2,
                                                  )  # opacity=.5)
            # surf2.enable_contours = True
            surf2.contour.auto_contours = False
            surf2.contour.contours = [threshold, data.max()]
            actors[side].append(surf2)
    return actors


def add_surf_map(niimg, sides=['left', 'right'], selected=False,
                 threshold=None, **kwargs):
    """ Project a volumetric data and plot it on the corresponding
        fsaverage surface.

        The kwargs are passed to mlab.triangular_mesh
    """
    actors = dict()
    for side in sides:
        data = surface.vol_to_surf(niimg, fsaverage['pial_%s' % side])
        this_actor = plot_on_surf(data, selected=selected,
                                  sides=[side, ], threshold=threshold,
                                  **kwargs)
        actors[side] = this_actor[side]
    return actors


###############################################################################

def plot_4d_image_surface(components, colors, output_dir):
    # Indices of the maps to outline
    indices = []
    mlab.options.offscreen = True

    fig = mlab.figure(bgcolor=(1, 1, 1))

    # Disable rendering to speed things up
    fig.scene.disable_render = True

    rng = np.random.RandomState(42)

    mask = datasets.load_mni152_brain_mask().get_data() > 0

    n_components = components.shape[-1]
    threshold = np.percentile(np.abs(components.get_data()[mask]),
                              100. * (1 - 1. / n_components))

    # To speed up when prototyping
    # components = image.index_img(components, slice(0, 5))
    actors = dict(left=[], right=[])
    delayed = []
    for i, (component, color) in enumerate(zip(
            image.iter_img(components),
            colors)):
        if i in indices:
            delayed.append((i, (component, color)))
        else:
            print('Component %i' % i)
            component = image.math_img('np.abs(img)', img=component)
            this_actors = add_surf_map(component, threshold=threshold,
                                       color=tuple(color[:3]),
                                       sides=['left', 'right'],
                                       selected=i in indices,
                                       inflate=1.001)
            actors['left'].extend(this_actors['left'])
            actors['right'].extend(this_actors['right'])
    for i, (component, color) in delayed:
        print('Component %i' % i)
        component = image.math_img('np.abs(img)', img=component)
        this_actors = add_surf_map(component, threshold=threshold,
                                   color=tuple(color[:3]),
                                   sides=['left', 'right'],
                                   selected=i in indices,
                                   inflate=1.001)
        actors['left'].extend(this_actors['left'])
        actors['right'].extend(this_actors['right'])

    # Plot the background
    for side in ['left', 'right']:
        depth = surface.load_surf_data(fsaverage['sulc_%s' % side])
        this_actors = plot_on_surf(-depth, sides=[side, ],
                                   colormap='gray', inflate=.995)
        actors[side].extend(this_actors[side])

    # Enable rendering
    fig.scene.disable_render = False

    save_views(fig, 'components_3d', actors,
               left_actors=actors['left'],
               right_actors=actors['right'], output_dir=output_dir)