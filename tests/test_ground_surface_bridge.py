"""Exercise DCS-native ground surface guards without a running DCS instance."""
import ctypes
import ctypes.util
from pathlib import Path
import unittest


class GroundSurfaceBridgeTest(unittest.TestCase):
    def test_rejects_water_and_runway_and_searches_for_land(self):
        library = ctypes.util.find_library("lua5.4")
        if not library:
            self.skipTest("Lua 5.4 shared library unavailable")
        lua = ctypes.CDLL(library)
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.lua_pcallk.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_longlong, ctypes.c_void_p,
        ]
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        state = lua.luaL_newstate()
        lua.luaL_openlibs(state)
        source = (Path(__file__).resolve().parents[1] / "missions" / "fow_bridge_generic.lua").read_text()
        script = """
        timer={getAbsTime=function() return 0 end,getTime=function() return 10 end,
            scheduleFunction=function() end}
        coalition={side={NEUTRAL=0,RED=1,BLUE=2},getGroups=function() return {} end,
            getStaticObjects=function() return {} end}
        world={event={S_EVENT_KILL=28},addEventHandler=function() end,
            getAirbases=function() return {} end}
        Group={Category={AIRPLANE=0,HELICOPTER=1,GROUND=2},getByName=function() return nil end}
        AI={Option={Ground={id={ROE=0},val={ROE={OPEN_FIRE=2,RETURN_FIRE=3,WEAPON_HOLD=4}}}}}
        trigger={action={outText=function() end}}
        coord={
            LLtoLO=function(lat,lon) return {x=lat*1000,y=0,z=lon*1000} end,
            LOtoLL=function(point) return point.x/1000,point.z/1000 end}
        land={SurfaceType={LAND=1,SHALLOW_WATER=2,WATER=3,ROAD=4,RUNWAY=5}}
        local surface=land.SurfaceType.WATER
        land.getSurfaceType=function(point)
            if point.x >= 250 then return land.SurfaceType.LAND end
            return surface
        end
        local added=0
        coalition.addGroup=function()
            added=added+1
            return {getCategory=function() return Group.Category.GROUND end,
                getName=function() return 'Safe' end,getID=function() return 1 end,
                getController=function() return {setOption=function() end} end}
        end
        """ + source + """
        local water=FoWBridge.spawnGroup('water',2,Group.Category.GROUND,
            {name='Water',units={{x=0,y=0}}})
        assert(water:find('GROUND_SURFACE_INVALID') and added==0)
        surface=land.SurfaceType.RUNWAY
        local runway=FoWBridge.spawnGroup('runway',2,Group.Category.GROUND,
            {name='Runway',units={{x=0,y=0}}})
        assert(runway:find('GROUND_SURFACE_INVALID') and added==0)
        surface=land.SurfaceType.WATER
        local found=FoWBridge.groundPosition('find',0,0,{{dx=0,dy=0}},1000,0)
        assert(found:find('"ok":true') and found:find('"lat":0.250000'))
        surface=land.SurfaceType.LAND
        local accepted=FoWBridge.spawnGroup('land',2,Group.Category.GROUND,
            {name='Land',units={{x=250,y=0}}})
        assert(accepted:find('SPAWN_ACCEPTED') and added==1)
        """
        try:
            rc = lua.luaL_loadstring(state, script.encode())
            if not rc:
                rc = lua.lua_pcallk(state, 0, 0, 0, 0, None)
            self.assertEqual(rc, 0, lua.lua_tolstring(state, -1, None))
        finally:
            lua.lua_close(state)


if __name__ == "__main__":
    unittest.main()
