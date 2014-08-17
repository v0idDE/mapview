# coding=utf-8
"""
MapView
=======

.. author:: Mathieu Virbel <mat@kivy.org>

MapView is a Kivy widget that display maps.
"""

__all__ = ["MapView", "MapSource"]
__version__ = "0.1"

from os.path import join, exists
from os import makedirs
from kivy.clock import Clock
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty, ObjectProperty
from kivy.graphics import Canvas, Color, Rectangle, PushMatrix, Translate, \
    PopMatrix
from collections import deque
from math import cos, sin, ceil, log, tan, pi, atan, exp
from random import choice
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from urllib2 import urlopen
from kivy.lang import Builder
from kivy.compat import string_types

MIN_LATITUDE = -90.
MAX_LATITUDE = 90.
MIN_LONGITUDE = -180.
MAX_LONGITUDE = 180.
MAX_WORKERS = 2
CACHE_DIR = "cache"

Builder.load_string("""
<MapView>:
    canvas.before:
        StencilPush
        Rectangle:
            pos: self.pos
            size: self.size
        StencilUse
    canvas.after:
        StencilUnUse
        Rectangle:
            pos: self.pos
            size: self.size
        StencilPop

""")

_downloader = None

def clamp(x, minimum, maximum):
    return max(minimum, min(x, maximum))


class Downloader(object):
    def __init__(self):
        super(Downloader, self).__init__()
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self._futures = []
        Clock.schedule_interval(self._check_executor, 1 / 60.)
        if not exists(CACHE_DIR):
            makedirs(CACHE_DIR)

    def download(self, tile):
        future = self.executor.submit(self._load_tile, tile)
        self._futures.append(future)

    def _load_tile(self, tile):
        if tile.state == "done":
            return
        cache_fn = tile.cache_fn
        if exists(cache_fn):
            return tile, cache_fn
        tile_y = tile.map_source.get_row_count(tile.zoom) - tile.tile_y - 1
        uri = tile.map_source.url.format(z=tile.zoom, x=tile.tile_x, y=tile_y,
                              s=choice(tile.map_source.subdomains))
        #print "Download {}".format(uri)
        data = urlopen(uri, timeout=5).read()
        with open(cache_fn, "wb") as fd:
            fd.write(data)
        #print "Downloaded {} bytes: {}".format(len(data), uri)
        return tile, cache_fn

    def _check_executor(self, dt):
        try:
            for future in as_completed(self._futures[:], 0):
                self._futures.remove(future)
                try:
                    result = future.result()
                except:
                    import traceback; traceback.print_exc()
                    # make an error tile?
                    continue
                if result is None:
                    continue
                tile, fn = result
                tile.source = fn
        except TimeoutError:
            pass


class Tile(Rectangle):
    @property
    def cache_fn(self):
        map_source = self.map_source
        fn = map_source.cache_fmt.format(
            image_ext=map_source.image_ext,
            cache_key=map_source.cache_key,
            **self.__dict__)
        return join(CACHE_DIR, fn)


class MapSource(object):
    # list of available providers
    # cache_key: (is_overlay, minzoom, maxzoom, url, attribution)
    providers = {
        "osm": (0, 0, 19, "http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            ""),
        "osm-hot": (0, 0, 19, "http://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
            ""),
        "osm-de": (0, 0, 18, "http://{s}.tile.openstreetmap.de/tiles/osmde/{z}/{x}/{y}.png",
            "Tiles @ OSM DE"),
        "osm-fr": (0, 0, 20, "http://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
            "Tiles @ OSM France"),
        "cyclemap": (0, 0, 17, "http://{s}.tile.opencyclemap.org/cycle/{z}/{x}/{y}.png",
            "Tiles @ Andy Allan"),
        "openseamap": (0, 0, 19, "http://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
            "Map data @ OpenSeaMap contributors"),
        "thunderforest-cycle": (0, 0, 19, "http://{s}.tile.thunderforest.com/cycle/{z}/{x}/{y}.png",
            "@ OpenCycleMap via OpenStreetMap"),
        "thunderforest-transport": (0, 0, 19, "http://{s}.tile.thunderforest.com/transport/{z}/{x}/{y}.png",
            "@ OpenCycleMap via OpenStreetMap"),
        "thunderforest-landscape": (0, 0, 19, "http://{s}.tile.thunderforest.com/landscape/{z}/{x}/{y}.png",
            "@ OpenCycleMap via OpenStreetMap"),
        "thunderforest-outdoors": (0, 0, 19, "http://{s}.tile.thunderforest.com/outdoors/{z}/{x}/{y}.png",
            "@ OpenCycleMap via OpenStreetMap"),
        "mapquest-osm": (0, 0, 19, "http://otile{s}.mqcdn.com/tiles/1.0.0/map/{z}/{x}/{y}.jpeg",
            "Tiles Courtesy of Mapquest", {"subdomains": "1234", "image_ext": "jpeg"}),
        "mapquest-aerial": (0, 0, 19, "http://oatile{s}.mqcdn.com/tiles/1.0.0/sat/{z}/{x}/{y}.jpeg",
            "Tiles Courtesy of Mapquest", {"subdomains": "1234", "image_ext": "jpeg"}),
        # more to add with
        # https://github.com/leaflet-extras/leaflet-providers/blob/master/leaflet-providers.js
    }

    def __init__(self,
        url="http://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        cache_key="osm", min_zoom=0, max_zoom=19, tile_size=256,
        image_ext="png", attribution="", subdomains="abc"):
        super(MapSource, self).__init__()
        self.url = url
        self.cache_key = cache_key
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        self.tile_size = tile_size
        self.image_ext = image_ext
        self.attribution = attribution
        self.subdomains = subdomains
        self.cache_fmt = "{cache_key}_{zoom}_{tile_x}_{tile_y}.{image_ext}"

    @staticmethod
    def from_provider(key):
        provider = MapSource.providers[key]
        options = {}
        is_overlay, min_zoom, max_zoom, url, attribution = provider[:5]
        if len(provider) > 5:
            options = provider[5]
        return MapSource(cache_key=key, min_zoom=min_zoom,
                         max_zoom=max_zoom, url=url, attribution=attribution,
                         **options)

    def get_x(self, zoom, lon):
        """Get the x position on the map using this map source's projection
        (0, 0) is located at the top left.
        """
        lon = clamp(lon, MIN_LONGITUDE, MAX_LONGITUDE)
        return ((lon + 180.) / 360. * pow(2., zoom)) * self.tile_size

    def get_y(self, zoom, lat):
        """Get the y position on the map using this map source's projection
        (0, 0) is located at the top left.
        """
        lat = clamp(-lat, MIN_LATITUDE, MAX_LATITUDE)
        lat = lat * pi / 180.
        return ((1.0 - log(tan(lat) + 1.0 / cos(lat)) / pi) / \
            2. * pow(2., zoom)) * self.tile_size

    def get_lon(self, zoom, x):
        """Get the longitude to the x position in the map source's projection
        """
        dx = x / float(self.tile_size)
        lon = dx / pow(2., zoom) * 360. - 180.
        return clamp(lon, MIN_LONGITUDE, MAX_LONGITUDE)

    def get_lat(self, zoom, y):
        """Get the latitude to the y position in the map source's projection
        """
        dy = y / float(self.tile_size)
        n = pi - 2 * pi * dy / pow(2., zoom)
        lat = -180. / pi * atan(.5 * (exp(n) - exp(-n)))
        return clamp(lat, MIN_LATITUDE, MAX_LATITUDE)

    def get_row_count(self, zoom):
        """Get the number of tiles in a row at this zoom level
        """
        if zoom == 0:
            return 1
        return 2 << (zoom - 1)

    def get_col_count(self, zoom):
        """Get the number of tiles in a col at this zoom level
        """
        if zoom == 0:
            return 1
        return 2 << (zoom - 1)

    def get_min_zoom(self):
        """Return the minimum zoom of this source
        """
        return 0

    def get_max_zoom(self):
        """Return the maximum zoom of this source
        """
        return 19

    def fill_tile(self, tile):
        """Add this tile to load within the downloader
        """
        if tile.state == "done":
            return
        if exists(tile.cache_fn):
            tile.source = tile.cache_fn
        else:
            global _downloader
            if _downloader is None:
                _downloader = Downloader()
            _downloader.download(tile)


class MapView(Widget):
    lon = NumericProperty()
    lat = NumericProperty()
    zoom = NumericProperty(5)
    map_source = ObjectProperty(MapSource())
    viewport_x = NumericProperty(0)
    viewport_y = NumericProperty(0)

    # Public API

    def unload(self):
        """Unload the view and all the layers.
        It also cancel all the remaining downloads.
        """
        self.remove_all_tiles()

    def center_on(self, lat, lon):
        """Center the map on the coordinate (lat, lon)
        """
        map_source = self.map_source
        zoom = self.zoom
        lon = clamp(lon, MIN_LONGITUDE, MAX_LONGITUDE)
        lat = clamp(lat, MIN_LATITUDE, MAX_LATITUDE)
        x = map_source.get_x(zoom, lon) - self.width / 2.
        y = map_source.get_y(zoom, lat) - self.height / 2.
        self._update_coords(x, y)
        self.remove_all_tiles()
        self.load_visible_tiles(False)

    def set_zoom_at(self, zoom, x, y):
        """Sets the zoom level, leaving the (x, y) at the exact same point
        in the view.
        """
        zoom = clamp(zoom,
                     self.map_source.get_min_zoom(),
                     self.map_source.get_max_zoom())
        if zoom == self.zoom:
            return

        x, y = self._get_x_y_for_zoom_level(zoom, x, y)
        self.zoom = zoom
        self._update_coords(x, y)
        self.remove_all_tiles()
        self.load_visible_tiles(False)


    # Private API

    def __init__(self, **kwargs):
        from kivy.base import EventLoop
        EventLoop.ensure_window()
        self.canvas = Canvas()
        with self.canvas:
            PushMatrix()
            self.g_translate = Translate()
            self.canvas_map = Canvas()
            PopMatrix()
        self._tiles = []
        self._tilemap = {}
        super(MapView, self).__init__(**kwargs)

    def _get_x_y_for_zoom_level(self, zoom, x, y):
        deltazoom = pow(2, zoom - self.zoom)
        nx = (self.viewport_x + x) * deltazoom - x
        ny = (self.viewport_y + y) * deltazoom - y
        return nx, ny

    def on_viewport_x(self, instance, value):
        p = self.g_translate.xy
        self.g_translate.xy = (-value, p[1])

    def on_viewport_y(self, instance, value):
        p = self.g_translate.xy
        self.g_translate.xy = (p[0], -value)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return
        d = None
        if "button" in touch.profile and touch.button in ("scrolldown", "scrollup"):
            d = 1 if touch.button == "scrollup" else -1
        elif touch.is_double_tap:
            d = 1
        if d is not None:
            zoom = clamp(self.zoom + d,
                              self.map_source.get_min_zoom(),
                              self.map_source.get_max_zoom())
            self.set_zoom_at(zoom, touch.x, touch.y)
        else:
            touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return
        self.lon = self.map_source.get_lon(self.zoom, self.viewport_x + self.width / 2.)
        self.lat = self.map_source.get_lat(self.zoom, self.viewport_y + self.height / 2.)
        self.viewport_x -= touch.dx
        self.viewport_y -= touch.dy
        self.load_visible_tiles(True)
        return True

    def _update_coords(self, x, y):
        zoom = self.zoom
        self.viewport_x = x
        self.viewport_y = y
        self.lon = self.map_source.get_lon(zoom, x + self.width / 2.)
        self.lat = self.map_source.get_lat(zoom, y + self.height / 2.)

    def load_visible_tiles(self, relocate=False):
        map_source = self.map_source
        zoom = self.zoom
        dirs = [0, 1, 0, -1, 0]

        size = map_source.tile_size
        max_x_end = map_source.get_col_count(zoom)
        max_y_end = map_source.get_row_count(zoom)
        x_count = int(ceil(self.width / float(size))) + 1
        y_count = int(ceil(self.height / float(size))) + 1

        tile_x_first = int(clamp(self.viewport_x / float(size), 0, max_x_end))
        tile_y_first = int(clamp(self.viewport_y / float(size), 0, max_y_end))
        tile_x_last = tile_x_first + x_count
        tile_y_last = tile_y_first + y_count
        tile_x_last = int(clamp(tile_x_last, tile_x_first, max_x_end))
        tile_y_last = int(clamp(tile_y_last, tile_y_first, max_y_end))

        x_count = tile_x_last - tile_x_first
        y_count = tile_y_last - tile_y_first

        #print "Range {},{} to {},{}".format(
        #    tile_x_first, tile_y_first,
        #    tile_x_last, tile_y_last)

        # Get rid of old tiles first
        for tile in self._tiles[:]:
            tile_x = tile.tile_x
            tile_y = tile.tile_y
            if tile_x < tile_x_first or tile_x >= tile_x_last or \
               tile_y < tile_y_first or tile_y >= tile_y_last:
                tile.state = "done"
                self.tile_map_set(tile_x, tile_y, False)
            elif relocate:
                tile.pos = (tile_x * size, tile_y * size)

        # Load new tiles if needed
        x = tile_x_first + x_count / 2 - 1
        y = tile_y_first + y_count / 2 - 1
        arm_max = max(x_count, y_count) + 2
        arm_size = 1
        turn = 0
        while arm_size < arm_max:
            for i in range(arm_size):
                if not self.tile_in_tile_map(x, y) and \
                   y >= tile_y_first and y < tile_y_last and \
                   x >= tile_x_first and x < tile_x_last:
                    self.load_tile(x, y, size, zoom)

                x += dirs[turn % 4 + 1]
                y += dirs[turn % 4]

            if turn % 2 == 1:
                arm_size += 1

            turn += 1

    def load_tile(self, x, y, size, zoom):
        map_source = self.map_source
        if self.tile_in_tile_map(x, y) or zoom != self.zoom:
            return
        self.load_tile_for_source(self.map_source, 1., size, x, y)
        # XXX do overlay support
        self.tile_map_set(x, y, True)

    def load_tile_for_source(self, map_source, opacity, size, x, y):
        tile = Tile(size=(size, size))
        tile.tile_x = x
        tile.tile_y = y
        tile.zoom = self.zoom
        tile.pos = (x * size, y * size)
        tile.map_source = map_source
        tile.state = "loading"
        map_source.fill_tile(tile)
        self.canvas_map.add(tile)
        self._tiles.append(tile)

    def remove_all_tiles(self):
        self.canvas_map.clear()
        for tile in self._tiles:
            tile.state = "done"
        del self._tiles[:]
        self._tilemap = {}

    def tile_map_set(self, tile_x, tile_y, value):
        key = tile_y * self.map_source.get_col_count(self.zoom) + tile_x
        if value:
            self._tilemap[key] = value
        else:
            self._tilemap.pop(key, None)

    def tile_in_tile_map(self, tile_x, tile_y):
        key = tile_y * self.map_source.get_col_count(self.zoom) + tile_x
        return key in self._tilemap

    def on_size(self, instance, size):
        self.remove_all_tiles()
        self.load_visible_tiles(False)
        self.center_on(self.lon, self.lat)

    def on_map_source(self, instance, source):
        if isinstance(source, string_types):
            self.map_source = MapSource.from_provider(source)
        elif isinstance(source, (tuple, list)):
            cache_key, min_zoom, max_zoom, url, attribution, options = source
            self.map_source = MapSource(url=url, cache_key=cache_key,
                                        min_zoom=min_zoom, max_zoom=max_zoom,
                                        attribution=attribution, **options)
        elif isinstance(source, MapSource):
            self.map_source = source
        else:
            raise Exception("Invalid map source provider")
        self.zoom = clamp(self.zoom,
                          self.map_source.min_zoom, self.map_source.max_zoom)
        self.remove_all_tiles()
        self.load_visible_tiles()

if __name__ == "__main__":
    from kivy.base import runTouchApp
    from kivy.lang import Builder
    try:
        root = Builder.load_string("""
#:import MapSource __main__.MapSource

<Toolbar@BoxLayout>:
    size_hint_y: None
    height: '48dp'
    padding: '4dp'
    spacing: '4dp'

    canvas:
        Color:
            rgba: .2, .2, .2, .6
        Rectangle:
            pos: self.pos
            size: self.size

RelativeLayout:

    MapView:
        id: mapview

    Toolbar:
        top: root.top
        Button:
            text: "Move to Lille, France"
            on_release: mapview.center_on(50.6394, 3.057)
        Button:
            text: "Move to Sydney, Autralia"
            on_release: mapview.center_on(-33.867, 151.206)
        Spinner:
            text: "mapnik"
            values: MapSource.providers.keys()
            on_text: mapview.map_source = self.text

    Toolbar:
        Label:
            text: "Longitude: {}".format(mapview.lon)
        Label:
            text: "Latitude: {}".format(mapview.lat)
        """)
        runTouchApp(root)
    finally:
        #root.ids.mapview.unload()
        pass
