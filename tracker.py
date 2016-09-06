#!/usr/bin/env python
tileset = r'http://3.base.maps.cit.api.here.com/maptile/2.1/maptile/newest/normal.day/{z}/{x}/{y}/256/png8?app_id=xhiqkgRI46elZ6OnVfot&app_code=mY1vlkf4B0kQ8cE9V36qVA&lg=eng'
kudos='Map &copy; 1987-2014 <a href="http://developer.here.com">HERE</a>'

"""
based on: pgoapi - Pokemon Go API
Copyright (c) 2016 tjado <https://github.com/tejado>

Author: TC    <reddit.com/u/Tr4sHCr4fT>
Version: 0.0.1-pre_alpha
"""
import folium
import json, argparse

from bottle import route, run, static_file
from time import strftime, localtime, sleep
from datetime import datetime, timedelta
from threading import Thread

from ext import *

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
    parser.add_argument("-u", "--username", help="Username")
    parser.add_argument("-p", "--password", help="Password")
    parser.add_argument("-l", "--location", help="Location")    
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

class Server(Thread):
    def run(self):
        run(host='localhost', port=5050, debug=False)
@route('/')
def serve_map():
    global origin, Pactive, covers, pokes, icons
    
    pokemap = folium.Map(location=[origin[0],origin[1]],zoom_start=12,tiles=tileset,attr=kudos)
    
    for c in covers:
        pass #folium.CircleMarker(c, radius=70, fill_color='#ffffff', fill_opacity=0).add_to(pokemap)
    
    for p in Pactive:
        if p[3] > 0: t = strftime('%H:%M:%S', time.localtime(int(p[3]/1000)))
        else: t = strftime('%H:%M:%S', time.localtime((time.time()+900)))
        folium.Marker(p[1], popup='%s - %s' % (pokes[p[2]],t), icon=icons[p[2]]).add_to(pokemap)
    
    if os.path.isfile('map.html'): os.remove('map.html')
    pokemap.save('map.html'); del pokemap
    return static_file('map.html', root='.')

@route('/icons/<filename>')
def serve_icon(filename):
    return static_file(filename, root='./icons/')

def main():
    
    config = init_config()
    if not config:
        return
    
    global origin, Pactive, covers, pokes, icons
    Ptargets,Pfound,Pactive,covers = [],[],[],[]
    
    log.info("Log'in...")
    api = api_init(config)

    ignore = get_ignorelist('ignore.txt')
    pokes = get_pokenames('pokes.txt')
    
    log.info("Loading icons..."); icons = [] 
    for i in xrange(0,151):
        icons.append(folium.features.CustomIcon('./icons/%d.png' % i))

    origin = get_pos_by_name(config.location)
    S = Server(); S.setDaemon(daemonic=True); S.start() 
    
    log.info('Generating Hexgrid...')
    grid = hex_spiral(origin[0], origin[1], 200, config.layers)
    
    while True:
        
        m = 1
        covers = []
        returntime = datetime.now() + timedelta(minutes=config.rhtime)
        
        for pos in grid:
            
            if datetime.now() > returntime: break
                        
            plat,plng = pos[0],pos[1]
            
            covers.append([plat,plng])
                    
            cell_ids = get_cell_ids(cover_circle(plat, plng, 210, 15))

            log.info('Scan location %d of %d' % (m,len(grid))); m+=1
            timestamps = [0,] * len(cell_ids)
            api.set_position(plat, plng, origin[2])
            response_dict = api.get_map_objects(latitude=plat, longitude=plng, since_timestamp_ms = timestamps, cell_id = cell_ids)
            if response_dict is None or len(response_dict) == 0: response_dict = api.get_map_objects(latitude=plat, longitude=plng, since_timestamp_ms = timestamps, cell_id = cell_ids)
            if response_dict is None or len(response_dict) == 0: continue
            
            Ctargets = []
            
            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'catchable_pokemons' in map_cell:
                    for poke in map_cell['catchable_pokemons']:
                        if poke['pokemon_id'] not in ignore and poke['encounter_id'] not in Pfound:
                            if [poke['encounter_id'],map_cell['s2_cell_id']] in Ptargets:
                                Ptargets.remove([poke['encounter_id'],map_cell['s2_cell_id']])
                            Pfound.append(poke['encounter_id'])
                            Pactive.append((poke['encounter_id'],[poke['latitude'],poke['longitude']],poke['pokemon_id'],poke['expiration_timestamp_ms']))
                            log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))

            for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                if 'nearby_pokemons' in map_cell:
                    for poke in map_cell['nearby_pokemons']:
                        if poke['pokemon_id'] in ignore:
                            log.info('{} nearby (ignored)'.format(pokes[poke['pokemon_id']], map_cell['s2_cell_id'])) # this will give you multiple messages for the same pokemon, should probably remove or use an ignore list
                        elif poke['encounter_id'] not in Pfound and [poke['encounter_id'],map_cell['s2_cell_id']] not in Ptargets:
                            Ptargets.append([poke['encounter_id'],map_cell['s2_cell_id']])
                            log.info('{} nearby (locked on!)'.format(pokes[poke['pokemon_id']],map_cell['s2_cell_id']))
                    del Ctargets[:]
                    for Ptarget in Ptargets:
                        if Ptarget[1] not in Ctargets:
                            Ctargets.append(Ptarget[1])

            if len(Ptargets) > 0:
                
                subgrid = hex_spiral(plat, plng, 70, 2)
                subgrid.pop(0) # already scanned in main thread
                
                tempsubgrid = []
                for tmp in subgrid:              
                    q = 0
                    for Ctarget in Ctargets:
                        q += circle_in_cell(CellId(Ctarget), tmp[0], tmp[1], 70, 12)    
                    if q > 0: tempsubgrid.append([tmp,q])
                
                tempsubgrid.sort(key=lambda q:q[1], reverse=True)
                
                subgrid = []
                for tmp in tempsubgrid:
                    subgrid.append(tmp[0])

                s=0
                for spos in subgrid:
                    if len(Ctargets) == 0: break

                    slat,slng = spos[0],spos[1]
                    
                    cell_ids = get_cell_ids(cover_circle(slat, slng, 75, 15))
                    s += 1
                    log.info('Looking closer for %d pokes, step %d (max %d)' % (len(Ptargets),s,len(subgrid)))

                    time.sleep(10)
                    timestamps = [0,] * len(cell_ids)
                    api.set_position(slat, slng, origin[2])
                    response_dict = api.get_map_objects(latitude=slat, longitude=slng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                    if response_dict is None or len(response_dict) == 0: response_dict = api.get_map_objects(latitude=slat, longitude=slng, since_timestamp_ms = timestamps, cell_id = cell_ids)
                    if response_dict is None or len(response_dict) == 0: continue

                    for map_cell in response_dict['responses']['GET_MAP_OBJECTS']['map_cells']:
                        if 'catchable_pokemons' in map_cell:
                            for poke in map_cell['catchable_pokemons']:
                                if poke['pokemon_id'] not in ignore and poke['encounter_id'] not in Pfound:
                                    if [poke['encounter_id'],map_cell['s2_cell_id']] in Ptargets:
                                        Ptargets.remove([poke['encounter_id'],map_cell['s2_cell_id']])
                                    Pfound.append(poke['encounter_id'])
                                    Pactive.append((poke['encounter_id'],[poke['latitude'],poke['longitude']],poke['pokemon_id'],poke['expiration_timestamp_ms']))
                                    log.info('{} at {}, {}!'.format(pokes[poke['pokemon_id']],poke['latitude'],poke['longitude']))
                            del Ctargets[:]
                            for Ptarget in Ptargets:
                                if Ptarget[1] not in Ctargets:
                                    Ctargets.append(Ptarget[1])

            time.sleep(10)

    S.join(60)
    log.info('Aborted or Logout.')

if __name__ == '__main__':
    main()