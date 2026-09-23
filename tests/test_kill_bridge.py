"""Exercise the Lua event handler without a running DCS instance."""
import ctypes
import ctypes.util
from pathlib import Path
import unittest


class KillBridgeTest(unittest.TestCase):
    def test_capture_missing_objects_and_duplicate_events(self):
        library = ctypes.util.find_library('lua5.4')
        if not library:
            self.skipTest('Lua 5.4 shared library unavailable')
        lua = ctypes.CDLL(library)
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.lua_pcallk.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_void_p]
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        state = lua.luaL_newstate()
        lua.luaL_openlibs(state)
        source = (Path(__file__).resolve().parents[1] / 'missions/fow_bridge_generic.lua').read_text()
        script = '''
        timer={getAbsTime=function() return 0 end,getTime=function() return 10 end}
        coalition={side={NEUTRAL=0,RED=1,BLUE=2}}
        world={event={S_EVENT_KILL=28},addEventHandler=function(h) handler=h end}
        ''' + source[:source.index('-- Only current, range-resolved')] + '''
        local target={getID=function() return 99 end,getCoalition=function() return 1 end,
            getTypeName=function() return 'MiG-29S' end}
        local attacker={getCoalition=function() return 2 end,getName=function() return 'Hornet' end,
            getGroup=function() return {getName=function() return 'CAP' end} end}
        local event={id=28,time=20,target=target,initiator=attacker,weapon_name='AIM-120C'}
        handler:onEvent(event);handler:onEvent(event)
        assert(#kill_reports==1)
        assert(kill_reports[1]:find('"attacker_group":"CAP"'))
        assert(kill_reports[1]:find('"weapon":"AIM%-120C"'))
        target.getID=function() return 100 end
        event.initiator=nil;event.weapon_name=nil
        handler:onEvent(event)
        assert(#kill_reports==2 and kill_reports[2]:find('"side":0'))
        event.target=nil;handler:onEvent(event);assert(#kill_reports==2)
        event.id=2;handler:onEvent(event);assert(#kill_reports==2)
        for i=101,310 do
            target.getID=function() return i end;event.target=target;event.id=28
            handler:onEvent(event)
        end
        assert(#kill_reports==200)
        '''
        try:
            # Compile the full bridge, then run the isolated handler checks.
            self.assertEqual(lua.luaL_loadstring(state, source.encode()), 0)
            rc = lua.luaL_loadstring(state, script.encode())
            if not rc:
                rc = lua.lua_pcallk(state, 0, 0, 0, 0, None)
            self.assertEqual(rc, 0, lua.lua_tolstring(state, -1, None))
        finally:
            lua.lua_close(state)
