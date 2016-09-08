#!/usr/bin/env python
"""
based on: pgoapi - Pokemon Go API
Copyright (c) 2016 tjado <https://github.com/tejado>

Author: TC    <reddit.com/u/Tr4sHCr4fT>
Version: 0.0.1-pre_alpha
"""
import os, re, json, argparse, logging, requests
from datetime import datetime, timedelta
from geopy.geocoders import GoogleV3
from s2sphere import CellId
from time import sleep
from random import randint
from threading import Thread

from pgoapi.exceptions import NotLoggedInException, AuthException
from core import api_init, get_pokelist, get_pokenames, hex_spiral, get_cell_ids, cover_circle, circle_in_cell, track


log = logging.getLogger(__name__)

def init_config():
    logging.basicConfig(level=logging.INFO, format='[%(levelname)5s] %(asctime)s %(message)s')
    parser = argparse.ArgumentParser()
    config_file = "config.json"

    load = {}
    if os.path.isfile(config_file):
        with open(config_file) as data:
            load.update(json.load(data))

    parser.add_argument("-a", "--auth_service", help="Auth Service ('ptc' or 'google')", default="ptc")
    parser.add_argument("--username", help="internal, dont input")
    parser.add_argument("--password", help="internal, dont input")
    parser.add_argument("-u1", "--username1", help="Username Main Account")
    parser.add_argument("-p1", "--password1", help="Password Main Account")
    parser.add_argument("-u2", "--username2", help="Username Sub Account")
    parser.add_argument("-p2", "--password2", help="Password Sub Account")
    parser.add_argument("-l", "--location", help="Location")
    parser.add_argument("-m", "--mode", help="Location", default='blacklist')
    parser.add_argument("--wh", help="Webhook host:port", default="localhost:4000")       
    parser.add_argument("-r", "--layers", help="Hex layers", default=5, type=int)
    parser.add_argument("-t", "--rhtime", help="max cycle time (minutes)", default=15, type=int)
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true', default=0)    
    config = parser.parse_args()

    for key in config.__dict__:
        if key in load and config.__dict__[key] == None:
            config.__dict__[key] = load[key]

    if config.debug:
        logging.getLogger("requests").setLevel(logging.DEBUG)
        logging.getLogger("pgoapi").setLevel(logging.DEBUG)
        logging.getLogger("rpc_api").setLevel(logging.DEBUG)
    else:
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("pgoapi").setLevel(logging.WARNING)
        logging.getLogger("rpc_api").setLevel(logging.WARNING)

    if config.auth_service not in ['ptc', 'google']:
        log.error("Invalid Auth service specified! ('ptc' or 'google')")
        return None

    return config


class TheSeeker(Thread):
    
    # generic constructor
    def __init__(self):
        Thread.__init__(self)
        self.log = logging.getLogger('Seeker')
        self.runs = True 
        global config 
        
        self.config = config
        self.lastscan = datetime.now()
        self.config.username = config.username1
        self.config.password = config.password1
        
    def run(self):
        global Pfound, Pque, Pcache
        global killswitch, grid
        
        log.info("Log'in...")
        api = api_init(self.config)
                
        if config.mode == 'blacklist':
            plist = get_pokelist('ignore.txt')
        elif config.mode == 'whitelist':
            plist = get_pokelist('watch.txt')
        pokes = get_pokenames('pokes.txt')
    
        while self.runs:
            
            m = 1
            returntime = datetime.now() + timedelta(minutes=config.rhtime)
         
            for pos in grid:
                
                if killswitch: self.runs = False 
                if datetime.now() > returntime: break
                
                Ptargets = []            
                plat,plng = pos[0],pos[1]
                cell_ids = get_cell_ids(cover_circle(plat, plng, 210, 15))
    
                while datetime.now() < (self.lastscan + timedelta(seconds=10)): sleep(0.5)
                
                log.info('Main: Scan location %d of %d' % (m,len(grid))); m+=1
                response_dict = None
                while response_dict is None:
                    timestamps = [0,] * len(cell_ids)
                    api.set_position(plat, plng, randint(5,25))
                    try: response_dict = api.get_map_objects(latitude=plat, longitude=plng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                    except NotLoggedInException, AuthException: api = None; api = api_init(self.config)
                    finally: self.lastscan = datetime.now()
 
                for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                    if 'catchable_pokemons' in map_cell:
                        for poke in map_cell['catchable_pokemons']:
                            if poke['encounter_id'] not in Pfound:
                                Pfound.append(poke['encounter_id']); Pcache.append(poke)
                                log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))
                    if 'nearby_pokemons' in map_cell:
                        for poke in map_cell['nearby_pokemons']:
                            if not track(poke['pokemon_id'],plist,config.mode) and poke['encounter_id'] not in Pfound:
                                Pfound.append(poke['encounter_id'])
                                log.info('{} nearby (ignored)'.format(pokes[poke['pokemon_id']], map_cell['s2_cell_id']))
                            elif track(poke['pokemon_id'],plist,config.mode) and poke['encounter_id'] not in Pfound and [poke['encounter_id'],map_cell['s2_cell_id']] not in Ptargets:
                                Ptargets.append([poke['encounter_id'],map_cell['s2_cell_id']])
                                log.info('{} nearby (locked on!)'.format(pokes[poke['pokemon_id']],map_cell['s2_cell_id']))
                Pque.append((pos,Ptargets))
                
                
            log.info('Back to Start.')


class TheFinder(Thread):
    
    # generic constructor
    def __init__(self):
        Thread.__init__(self)
        self.log = logging.getLogger('Seeker')
        self.runs = True
          
        global config
        self.config = config
        self.config.username = config.username2
        self.config.password = config.password2
        
    def run(self):
        
        global killswitch
        global Pfound, Pcache, Pque
                    
        if config.mode == 'blacklist':
            plist = get_pokelist('ignore.txt')
        elif config.mode == 'whitelist':
            plist = get_pokelist('watch.txt')
        pokes = get_pokenames('pokes.txt')
    
        log.info("Log'in...")
        api = api_init(self.config)
        self.lastscan = datetime.now()
                    
        while self.runs:
            
            if len(Pque) > 0:
                
                pos, Ptargets = Pque[0]
                
                initsubgrid = hex_spiral(pos[0],pos[1], 70, 2)
                initsubgrid.pop(0) # already scanned in main thread

                s=1
                Sdone = []
                
                while len(Ptargets) > 0:
                    
                    if killswitch: self.runs = False; break
                    
                    Ctargets = []
                    for Ptarget in Ptargets:
                        if Ptarget[1] not in Ctargets:
                            Ctargets.append(Ptarget[1])
                    if len(Ctargets) < 1: break
                        
                    tempsubgrid = []
                    for tmp in initsubgrid:              
                        q = 0
                        for Ctarget in Ctargets:
                            q += circle_in_cell(CellId(Ctarget), tmp[0], tmp[1], 70, 12)    
                        if q > 0 and tmp not in Sdone: tempsubgrid.append([tmp,q])
                    
                    if len(tempsubgrid) < 1: break
                    subgrid = sorted(tempsubgrid, key=lambda q:q[1], reverse=True)
    
                    spos = subgrid[0][0]
                    slat,slng = spos[0],spos[1]
                    cell_ids = get_cell_ids(cover_circle(slat, slng, 75, 15))
                    
                    while datetime.now() < (self.lastscan + timedelta(seconds=10)): sleep(0.5)
                    
                    log.info('Sub: Looking closer for %d pokes, step %d (max %d)' % (len(Ptargets),s,len(subgrid)))

                    response_dict = None
                    while response_dict is None:
                        timestamps = [0,] * len(cell_ids)
                        api.set_position(slat, slng, randint(5,25))
                        try: response_dict = api.get_map_objects(latitude=slat, longitude=slng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                        except NotLoggedInException, AuthException: api = None; api = api_init(self.config)
                        finally: self.lastscan = datetime.now()

                    for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                        if 'catchable_pokemons' in map_cell:
                            for poke in map_cell['catchable_pokemons']:
                                if poke['encounter_id'] not in Pfound:
                                    if [poke['encounter_id'],map_cell['s2_cell_id']] in Ptargets:
                                        Ptargets.remove([poke['encounter_id'],map_cell['s2_cell_id']])
                                    Pfound.append(poke['encounter_id']); Pcache.append(poke)
                                    log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))
                        if 'nearby_pokemons' in map_cell:
                            for poke in map_cell['nearby_pokemons']:
                                if not track(poke['pokemon_id'],plist,config.mode) and poke['encounter_id'] not in Pfound:
                                    Pfound.append(poke['encounter_id'])
                                    log.info('{} nearby (ignored)'.format(pokes[poke['pokemon_id']], map_cell['s2_cell_id']))
                                elif track(poke['pokemon_id'],plist,config.mode) and poke['encounter_id'] not in Pfound and [poke['encounter_id'],map_cell['s2_cell_id']] not in Ptargets:
                                    Ptargets.append([poke['encounter_id'],map_cell['s2_cell_id']])
                                    log.info('{} nearby (locked on!)'.format(pokes[poke['pokemon_id']],map_cell['s2_cell_id']))
                    
                    Sdone.append(spos)
                    s += 1
                
                Pque.pop(0)
#
    
def main():
    global config
    
    config = init_config()
    if not config:
        return

    geolocator = GoogleV3()
    prog = re.compile("^(\-?\d+\.\d+)?,\s*(\-?\d+\.\d+?)$")
    res = prog.match(config.location)
    if res: olat, olng, alt = float(res.group(1)), float(res.group(2)), 0
    else:
        loc = geolocator.geocode(config.location, timeout=10)
        if loc:
            log.info("Location for '%s' found: %s", config.location, loc.address)
            log.info('Coordinates (lat/long/alt) for location: %s %s %s', loc.latitude, loc.longitude, loc.altitude)
            olat, olng, alt = loc.latitude, loc.longitude, loc.altitude; del loc
        else: return
    del alt
    
    global grid
    log.info('Generating Hexgrid...')
    grid = hex_spiral(olat, olng, 200, config.layers)
    
    global Pque, Pfound, Pcache
    Pque,Pfound,Pcache = [],[],[]
    
    global killswitch
    killswitch = False
    
    S = TheSeeker(); F = TheFinder()
    S.start();  sleep(3);  F.start()

    try:
        while True:
            if len(Pcache) > 0:
                Psend = Pcache; Pcache = []
                for p in Psend:
                    p['spawnpoint_id'] = p['spawn_point_id']; del p['spawn_point_id']
                    p['disappear_time'] = (p['expiration_timestamp_ms']/1000); del p['expiration_timestamp_ms']
                    d = {"type": "pokemon", "message": p }
                    try: requests.post('http://%s/' % config.wh, json=d)
                    except Exception as e: log.error(e); continue
            sleep(5)
    except KeyboardInterrupt: log.info('Aborting...')
    
    killswitch = True
    S.join(60); F.join(60)
    
    log.info('Aborted or Crashed.')

if __name__ == '__main__':
    main()