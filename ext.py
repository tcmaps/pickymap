import re, os, sys, platform, time, math, logging

from geopy.geocoders import GoogleV3
from geographiclib.geodesic import Geodesic
from s2sphere import Cell, CellId, Angle, LatLng, Cap, RegionCoverer

from pgoapi.exceptions import AuthException
from pgoapi.pgoapi import PGoApi

log = logging.getLogger(__name__)


def get_pos_by_name(location_name):
    prog = re.compile("^(\-?\d+\.\d+)?,\s*(\-?\d+\.\d+?)$")
    res = prog.match(location_name)
    if res:
        latitude, longitude, altitude = float(res.group(1)), float(res.group(2)), 0
    else:
        geolocator = GoogleV3()
        loc = geolocator.geocode(location_name, timeout=10)
        if loc:
            log.info("Location for '%s' found: %s", location_name, loc.address)
            log.info('Coordinates (lat/long/alt) for location: %s %s %s', loc.latitude, loc.longitude, loc.altitude)
            latitude, longitude, altitude = loc.latitude, loc.longitude, loc.altitude
        else:
            return None

    return (latitude, longitude, altitude)

def sub_cell(cell,i=0,dist=25):
    
    g = Geodesic.WGS84  # @UndefinedVariable
    olat = CellId.to_lat_lng(cell).lat().degrees
    olng = CellId.to_lat_lng(cell).lng().degrees

    p = g.Direct(olat, olng,(45+(90*i)),dist)
    c = CellId.from_lat_lng(LatLng.from_degrees(p['lat2'],p['lon2']))
    
    return c.parent(cell.level()+1)

def get_cell_edge(cell, edge=0):
    
    cell_edge = LatLng.from_point(cell.get_vertex(edge))
    
    return cell_edge

def get_cell_edges(cellid):
    
    cell = Cell(cellid)
    cell_edges = []
    
    for i in range(4):
        cell_edges.append(get_cell_edge(cell,i))
    
    return cell_edges
    
def point_in_cell(cell,lat,lng):
        ll = LatLng.from_degrees(lat, lng)
        if CellId.from_lat_lng(ll).parent(cell.level()) == cell: return True
        else: return False
        
def circle_in_cell(cell, lat, lng, radius, res=8):
    g = Geodesic.WGS84  # @UndefinedVariable
    
    q = 0
    for i in xrange(res):
        p = g.Direct(lat, lng, i * (360/res), radius)
        if point_in_cell(cell, p['lat2'], p['lon2']): q += 1
        
    return float(float(q)/float(res))
    
def get_cell_ids(cells):
    cell_ids = sorted([x.id() for x in cells])
    return cell_ids

def cover_circle(lat, lng, radius, level=15):
    EARTH = 6371000
    region = Cap.from_axis_angle(
             LatLng.from_degrees(lat, lng).to_point(),
             Angle.from_degrees(360*radius/(2*math.pi*EARTH)))
    coverer = RegionCoverer()
    coverer.min_level = level
    coverer.max_level = level
    cells = coverer.get_covering(region)
    return cells

def getEarthRadius(latrad):
    return (1.0 / (((math.cos(latrad)) / 6378137.0) ** 2 + ((math.sin(latrad)) / 6356752.3) ** 2)) ** (1.0 / 2)

def hex_spiral(lat_org, lng_org, dist, layers):
    latrad = lat_org * math.pi / 180

    x_un = 1.5 * dist / getEarthRadius(latrad) / math.cos(latrad) * 0.999 * 180 / math.pi # unity vector in x direction in degrees
    y_un = 1.0 * 3.0 ** 0.5 / 2.0 * dist / getEarthRadius(latrad) * 0.999 * 180 / math.pi # unity vector in y direction in degrees
    
    grid = [(lat_org,lng_org)]

    for a in range(1, layers+1):
        for s in range(0, 6): # 6 sides
            for i in range(0, a): #a tiles per side
                if s == 0:
                    lat = lat_org + y_un * (-2 * a + i)
                    lng = lng_org + x_un * i
                elif s == 1:
                    lat = lat_org + y_un * (-a + 2 * i)
                    lng = lng_org + x_un * a
                elif s == 2:
                    lat = lat_org + y_un * (a + i)
                    lng = lng_org + x_un * (a - i)
                elif s == 3:
                    lat = lat_org - y_un * (-2 * a + i)
                    lng = lng_org - x_un * i
                elif s == 4:
                    lat = lat_org - y_un * (-a + 2 * i)
                    lng = lng_org - x_un * a
                else:  # if s==5:
                    lat = lat_org - y_un * (a + i)
                    lng = lng_org - x_un * (a - i)

                grid.append((lat,lng))
    return grid

def cell_spiral(lat, lng, dist, level=15, step=100, res=3.6):
    cells = []

    g = Geodesic.WGS84  # @UndefinedVariable
    
    for i in range(0,dist,step):
        for rad in range(int(360/res)):
            p = g.Direct(lat, lng, rad*res, i)
            c = CellId.from_lat_lng(LatLng.from_degrees(p['lat2'],p['lon2']))
            c = c.parent(level)
            if c not in cells: cells.append(c)

    grid = []
    for cell in cells:
        grid.extend(get_cell_edges(cell))

    return grid

class AccountBannedException(AuthException):
    pass

def api_init(account):
    api = PGoApi()
    
    try:
        api.set_position(360,360,0)  
        api.set_authentication(provider = account.auth_service,
                               username = account.username, password =  account.password)
        api.activate_signature(get_encryption_lib_path()); time.sleep(1); api.get_player()
    
    except AuthException:
        log.error('Login for %s:%s failed - wrong credentials?' % (account.username, account.password))
        return None
    
    else:
        time.sleep(1); response = api.get_inventory()
        
        if response:
            if 'status_code' in response:
                if response['status_code'] == 1 or response['status_code'] == 2: return api
                
                elif response['status_code'] == 3:
                    # try to accept ToS
                    time.sleep(5); response = api.mark_tutorial_complete(tutorials_completed = 0,
                                    send_marketing_emails = False, send_push_notifications = False)                    

                    if response['status_code'] == 1 or response['status_code'] == 2:
                        print('Accepted TOS for %s' % account.username)
                        return api
                    
                    elif response['status_code'] == 3:
                        print('Account %s BANNED!' % account.username)
                        raise AccountBannedException
                
    return None

def get_encryption_lib_path():
    # win32 doesn't mean necessarily 32 bits
    if sys.platform == "win32" or sys.platform == "cygwin":
        if platform.architecture()[0] == '64bit':
            lib_name = "encrypt64bit.dll"
        else:
            lib_name = "encrypt32bit.dll"

    elif sys.platform == "darwin":
        lib_name = "libencrypt-osx-64.so"

    elif os.uname()[4].startswith("arm") and platform.architecture()[0] == '32bit':  # @UndefinedVariable
        lib_name = "libencrypt-linux-arm-32.so"

    elif os.uname()[4].startswith("aarch64") and platform.architecture()[0] == '64bit':  # @UndefinedVariable
        lib_name = "libencrypt-linux-arm-64.so"

    elif sys.platform.startswith('linux'):
        if "centos" in platform.platform():
            if platform.architecture()[0] == '64bit':
                lib_name = "libencrypt-centos-x86-64.so"
            else:
                lib_name = "libencrypt-linux-x86-32.so"
        else:
            if platform.architecture()[0] == '64bit':
                lib_name = "libencrypt-linux-x86-64.so"
            else:
                lib_name = "libencrypt-linux-x86-32.so"

    elif sys.platform.startswith('freebsd'):
        lib_name = "libencrypt-freebsd-64.so"

    else:
        err = "Unexpected/unsupported platform '{}'".format(sys.platform)
        log.error(err)
        raise Exception(err)
    
    # check for lib in root dir or PATH
    if os.path.isfile(lib_name):
        return lib_name
    
    test_paths = ["../pgoapi/magiclib","../pgoapi/libencrypt","../magiclib","../libencrypt"]
    
    for test_path in test_paths:
        lib_path = os.path.join(os.path.dirname(__file__), test_path, lib_name)
        if os.path.isfile(lib_path): return lib_path

    err = "Could not find [{}] encryption library '{}'".format(sys.platform, lib_name)
    log.error(err)
    raise Exception(err)

def get_pokenames(filename):
    plist = []
    f = open(filename,'r')
    for l in f.readlines():
        plist.append(l.strip())
    return plist
    
def get_ignorelist(filename):
    wlist = []
    f = open(filename,'r')
    for l in f.readlines():
        wlist.append(int(l.strip()))
    return wlist
