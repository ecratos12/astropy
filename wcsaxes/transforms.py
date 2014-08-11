# Note: This file incldues code dervived from pywcsgrid2
#
# This file contains Matplotlib transformation objects (e.g. from pixel to world
# coordinates, but also world-to-world).

import abc
import numpy as np
from matplotlib.path import Path
from matplotlib.transforms import Transform
from astropy import units as u
from astropy.wcs import WCS
from astropy.extern import six
from .utils import get_coordinate_frame


@six.add_metaclass(abc.ABCMeta)
class CurvedTransform(Transform):
    """
    Abstract base class for non-affine curved transforms
    """

    input_dims = 2
    output_dims = 2
    is_separable = False

    def transform_path(self, path):
        """
        Transform a Matplotlib Path

        Parameters
        ----------
        path : :class:`~matplotlib.path.Path`
            The path to transform

        Returns
        -------
        path : :class:`~matplotlib.path.Path`
            The resulting path
        """
        return Path(self.transform(path.vertices), path.codes)

    transform_path_non_affine = transform_path

    @abc.abstractmethod
    def transform(self, input):
        raise NotImplemented("")

    @abc.abstractmethod
    def inverted(self):
        raise NotImplemented("")


class WCSWorld2PixelTransform(CurvedTransform):

    """
    WCS transformation from world to pixel coordinates
    """

    def __init__(self, wcs, slice=None):
        super(WCSWorld2PixelTransform, self).__init__()
        self.wcs = wcs
        if self.wcs.wcs.naxis > 2:
            if slice is None:
                raise ValueError("WCS has more than 2 dimensions, so ``slice`` should be set")
            elif len(slice) != self.wcs.wcs.naxis:
                raise ValueError("slice should have as many elements as WCS "
                                 "has dimensions (should be {0})".format(self.wcs.wcs.naxis))
            else:
                self.slice = slice
                self.x_index = slice.index('x')
                self.y_index = slice.index('y')
        else:
            self.slice = None

    def transform(self, world):
        """
        Transform world to pixel coordinates. You should pass in a NxM array
        where N is the number of points to transform, and M is the number of
        dimensions in the WCS. This then returns the (x, y) pixel coordinates
        as a Nx2 array.
        """

        if world.shape[1] != self.wcs.wcs.naxis:
            raise ValueError("Second dimension of input values should match number of WCS coordinates")

        pixel = self.wcs.wcs_world2pix(world, 1) - 1

        if self.slice is None:
            return pixel
        else:
            return pixel[:,(self.x_index, self.y_index)]


    transform_non_affine = transform

    def inverted(self):
        """
        Return the inverse of the transform
        """
        return WCSPixel2WorldTransform(self.wcs, slice=self.slice)


class WCSPixel2WorldTransform(CurvedTransform):

    """
    WCS transformation from pixel to world coordinates
    """

    def __init__(self, wcs, slice=None):
        super(WCSPixel2WorldTransform, self).__init__()
        self.wcs = wcs
        self.slice = slice
        if self.slice is not None:
            self.x_index = slice.index('x')
            self.y_index = slice.index('y')

    def get_coord_slices(self, xmin, xmax, ymin, ymax, nx, ny):
        """
        Get a coordinate slice
        """
        x = np.linspace(xmin, xmax, nx)
        y = np.linspace(ymin, ymax, ny)
        Y, X = np.meshgrid(y, x)
        pixel = np.array([X.ravel(), Y.ravel()]).transpose()
        world = self.transform(pixel)
        return X, Y, [world[:,i].reshape(nx, ny).transpose() for i in range(self.wcs.wcs.naxis)]

    def transform(self, pixel):
        """
        Transform pixel to world coordinates. You should pass in a Nx2 array
        of (x, y) pixel coordinates to transform to world coordinates. This
        will then return an NxM array where M is the number of dimensions in
        the WCS
        """

        if self.slice is None:
            pixel_full = pixel.copy()
        else:
            pixel_full = []
            for index in self.slice:
                if index == 'x':
                    pixel_full.append(pixel[:, 0])
                elif index == 'y':
                    pixel_full.append(pixel[:, 1])
                else:
                    pixel_full.append(index)
            pixel_full = np.array(np.broadcast_arrays(*pixel_full)).transpose()

        pixel_full += 1

        world = self.wcs.wcs_pix2world(pixel_full, 1)

        # At the moment, one has to manually check that the transformation
        # round-trips, otherwise it should be considered invalid.
        pixel_check = self.wcs.wcs_world2pix(world, 1)
        invalid = np.any(np.abs(pixel_check - pixel_full) > 1., axis=1)
        world[invalid] = np.nan

        return world

    transform_non_affine = transform

    def inverted(self):
        """
        Return the inverse of the transform
        """
        return WCSWorld2PixelTransform(self.wcs, slice=self.slice)


try:
    
    from astropy.coordinates import SkyCoord
    from astropy.coordinates import frame_transform_graph

    class CoordinateTransform(CurvedTransform):
        def __init__(self, input_system, output_system):
            super(CoordinateTransform, self).__init__()
            self._input_system_name = input_system
            self._output_system_name = output_system

            if isinstance(self._input_system_name, WCS):
                self.input_system = get_coordinate_frame(self._input_system_name)
            elif isinstance(self._input_system_name, six.string_types):
                self.input_system = frame_transform_graph.lookup_name(self._input_system_name)
                if self.input_system is None:
                    raise ValueError("Frame {0} not found".format(self._input_system_name))

            if isinstance(self._output_system_name, WCS):
                self.output_system = get_coordinate_frame(self._output_system_name)
            elif isinstance(self._output_system_name, six.string_types):
                self.output_system = frame_transform_graph.lookup_name(self._output_system_name)
                if self.output_system is None:
                    raise ValueError("Frame {0} not found".format(self._output_system_name))

            if self.output_system == self.input_system:
                self.same_frames = True
            else:
                self.same_frames = False

        @property
        def same_frames(self):
            return self._same_frames

        @same_frames.setter
        def same_frames(self, same_frames):
            self._same_frames = same_frames

        def transform(self, input_coords):
            """
            Transform one set of coordinates to another
            """
            if self.same_frames:
                return input_coords

            x_in, y_in = input_coords[:, 0], input_coords[:, 1]

            c_in = SkyCoord(x_in, y_in, unit=(u.deg, u.deg), frame=self.input_system)

            c_out = c_in.transform_to(self.output_system)

            return np.concatenate((c_out.spherical.lon.deg[:, np.newaxis], c_out.spherical.lat.deg[:, np.newaxis]), 1)

        transform_non_affine = transform

        def inverted(self):
            """
            Return the inverse of the transform
            """
            return CoordinateTransform(self._output_system_name, self._input_system_name)

except ImportError:

    class CoordinateTransform(CurvedTransform):

        def __init__(self, input_system, output_system):
            super(CoordinateTransform, self).__init__()
            from astropy.coordinates import FK5, Galactic
            self._input_system_name = input_system
            self._output_system_name = output_system

            if isinstance(self._input_system_name, WCS):
                self.input_system = get_coordinate_frame(self._input_system_name)
            elif isinstance(self._input_system_name, six.string_types):
                if self._input_system_name == 'fk5':
                    self.input_system = FK5
                elif self._input_system_name == 'galactic':
                    self.input_system = Galactic
                else:
                    raise NotImplemented("frame {0} not implemented".format(self._input_system_name))

            if isinstance(self._output_system_name, WCS):
                self.output_system = get_coordinate_frame(self._output_system_name)
            elif isinstance(self._output_system_name, six.string_types):
                if self._output_system_name == 'fk5':
                    self.output_system = FK5
                elif self._output_system_name == 'galactic':
                    self.output_system = Galactic
                else:
                    raise NotImplemented("frame {0} not implemented".format(self._output_system_name))

            if self.output_system == self.input_system:
                self.same_frames = True
            else:
                self.same_frames = False

        @property
        def same_frames(self):
            return self._same_frames

        @same_frames.setter
        def same_frames(self, same_frames):
            self._same_frames = same_frames

        def transform(self, input_coords):
            """
            Transform one set of coordinates to another
            """
            if self.same_frames:
                return input_coords

            x_in, y_in = input_coords[:, 0], input_coords[:, 1]

            c_in = self.input_system(x_in, y_in, unit=(u.deg, u.deg))

            c_out = c_in.transform_to(self.output_system)

            return np.concatenate((c_out.lonangle.deg[:, np.newaxis], c_out.latangle.deg[:, np.newaxis]), 1)

        transform_non_affine = transform

        def inverted(self):
            """
            Return the inverse of the transform
            """
            return CoordinateTransform(self._output_system_name, self._input_system_name)