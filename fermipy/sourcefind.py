import numpy as np
import scipy.ndimage
from astropy.coordinates import SkyCoord

import fermipy.config
import fermipy.defaults as defaults
import fermipy.utils as utils
from fermipy.utils import Map
from fermipy.logger import Logger
from fermipy.logger import logLevel


def find_peaks(input_map, threshold, min_separation=1.0):
    """Find peaks in a 2-D map object that have amplitude larger than
    `threshold` and lie a distance at least `min_separation` from another
    peak of larger amplitude.  The implementation of this method uses
    `~scipy.ndimage.filters.maximum_filter`.

    Parameters
    ----------
    input_map : `~fermipy.utils.Map`

    threshold : float

    min_separation : float
       Radius of region size in degrees.  Sets the minimum allowable
       separation between peaks.

    Returns
    -------
    peaks : list
       List of dictionaries containing the location and amplitude of
       each peak.
    """

    data = input_map.counts

    region_size_pix = int(min_separation/max(input_map.wcs.wcs.cdelt))
    deltaxy = utils.make_pixel_offset(region_size_pix*2+3)
    deltaxy *= max(input_map.wcs.wcs.cdelt)
    region = deltaxy < min_separation

#    print region.shape
#    import matplotlib.pyplot as plt
#    plt.figure(); plt.imshow(region,interpolation='nearest')    
#    local_max = scipy.ndimage.filters.maximum_filter(data, region_size) == data
    local_max = scipy.ndimage.filters.maximum_filter(data,
                                                     footprint=region) == data
    local_max[data < threshold] = False

    labeled, num_objects = scipy.ndimage.label(local_max)
    slices = scipy.ndimage.find_objects(labeled)

    peaks = []
    for s in slices:
        skydir = SkyCoord.from_pixel(s[1].start, s[0].start,
                                     input_map.wcs)
        peaks.append({'ix': s[1].start,
                      'iy': s[0].start,
                      'skydir': skydir,
                      'amp': data[s[0].start, s[1].start]})

    return sorted(peaks, key=lambda t: t['amp'], reverse=True)


class SourceFinder(fermipy.config.Configurable):

    defaults = dict(defaults.sourcefind.items(),
                    fileio=defaults.fileio,
                    logging=defaults.logging)

    def __init__(self, config=None, **kwargs):
        fermipy.config.Configurable.__init__(self, config, **kwargs)
        self.logger = Logger.get(self.__class__.__name__,
                                 self.config['fileio']['logfile'],
                                 logLevel(self.config['logging']['verbosity']))

    def find_sources(self, gta, prefix, **kwargs):
        """
        Find new sources.
        """

        o = {'sources': []}
        
        max_iter = kwargs.get('max_iter', self.config['max_iter'])
        for i in range(max_iter):
            srcs = self._iterate(gta, i, **kwargs)

            self.logger.info('Found %i sources in iteration %i.'%(len(srcs),i))
            
            o['sources'] += srcs
            if len(srcs) == 0:
                break

        return o

    def _iterate(self, gta, iiter, **kwargs):

        src_dict = {'Index': 2.0,
                    'SpatialModel': 'PointSource',
                    'Prefactor': 1E-13}
        
        threshold = kwargs.get('sqrt_ts_threshold',
                               self.config['sqrt_ts_threshold'])
        min_separation = kwargs.get('min_separation',
                                    self.config['min_separation'])
        sources_per_iter = kwargs.get('sources_per_iter',
                                      self.config['sources_per_iter'])
        
        m = gta.tsmap('sourcefind_%02i'%iiter, model=src_dict, make_fits=False,
                      **kwargs)
        amp = m['amplitude']
        peaks = find_peaks(m['sqrt_ts'], threshold, min_separation)

        names = []
        for p in peaks[:sources_per_iter]:
            name = utils.create_source_name(p['skydir'])
            src_dict = {'Index': 2.0,
                        'Prefactor': 1E-13*amp.counts[p['iy'], p['ix']],
                        'SpatialModel': 'PointSource',
                        'ra': p['skydir'].icrs.ra.deg,
                        'dec': p['skydir'].icrs.dec.deg}

            names += [name]
            gta.add_source(name, src_dict, free=True)

        for name in names:
            gta.free_source(name,False)

        # Re-fit spectral parameter of each source individually
        for name in names:
            gta.free_source(name,True)
            gta.fit()
            gta.free_source(name,False)
            
        srcs = []
        for name in names:
            srcs.append(gta.roi[name])

        return srcs
            
    def _fit_source(self, gta, **kwargs):

        localize = kwargs.get('localize',self.config['localize'])
        pass