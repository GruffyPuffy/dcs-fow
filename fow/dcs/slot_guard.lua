-- Slot availability is supplied by the FoW server. This script only enforces it.
FoWSlotAccess = FoWSlotAccess or {}

local original_handle = FoWBridge.handle

function FoWBridge.setSlotAccess(id, slots, enabled)
    if type(slots) ~= 'table' or type(enabled) ~= 'boolean' then
        return reply(id, false, 'INVALID_SLOT_ACCESS')
    end
    local changed = 0
    for _, group_name in pairs(slots) do
        if type(group_name) ~= 'string' or FoWSlotAccess[group_name] == nil then
            return reply(id, false, 'UNKNOWN_SLOT')
        end
        FoWSlotAccess[group_name] = enabled
        changed = changed + 1
    end
    return reply(id, true, 'SLOT_ACCESS_SET:' .. changed)
end

function FoWBridge.handle(request)
    if request.op == 'set_slot_access' then
        return FoWBridge.setSlotAccess(request.id, request.slots, request.enabled)
    end
    return original_handle(request)
end

local slot_guard = {}
function slot_guard:onEvent(event)
    if event.id ~= world.event.S_EVENT_BIRTH or not event.initiator then return end
    local player_name = safe_call(event.initiator, 'getPlayerName')
    local group = safe_call(event.initiator, 'getGroup')
    if not player_name or not group or FoWSlotAccess[group:getName()] ~= false then return end

    trigger.action.outTextForGroup(group:getID(), 'This base is not available yet.', 10)
    pcall(function() event.initiator:destroy() end)
    if net and net.get_player_list and net.get_name and net.force_player_slot then
        for _, player_id in pairs(net.get_player_list() or {}) do
            if net.get_name(player_id) == player_name then
                pcall(net.force_player_slot, player_id, 0, '')
                break
            end
        end
    end
end
world.addEventHandler(slot_guard)