"""Pure-Lua WoW runtime environment bootstrap (created 2026-11-11).

Invariants owned by this file:
- Everything addon code can observe about the fake client (WoW's Lua stdlib extensions,
  frames and widgets, the slash-command table, the error handler, and the strict
  ``_G``/``C_*``/``Enum``/``Constants`` metatables) is installed by one pure Lua 5.1
  bootstrap, so the semantics addons see are Lua semantics, not Python objects wearing a
  Lua-shaped mask.
- The bootstrap takes every fact Python owns (the virtual clock, which events, templates
  and widget methods exist, how unknown globals and ``C_*`` members resolve, and where
  unhandled errors are recorded) through a single ``bridge`` table of callbacks, so this
  file invents no API knowledge of its own.
- Strictness is armed last and explicitly: the WoW stdlib globals and frames are
  installed first, and only ``controller.arm_strict_globals()`` puts a metatable on
  ``_G``, so bootstrap code never trips over the strictness meant for addon code.
- A frame is a plain Lua table addon code can freely annotate; engine state lives in a
  hidden side table keyed by the frame, so addon fields can never corrupt the widget
  state the client tracks.
"""

from __future__ import annotations

from typing import Any

# [2026-11-11 T-007] The bootstrap is one chunk returning an installer function so that
# runtime.execute hands Python a callable: installing is installer(bridge), and the
# returned controller is the only handle Python needs to fire events, run slash commands
# and arm strictness. Bridge callbacks are captured into locals at install time, so the
# strict _G metatable installed later can never intercept the engine's own lookups.
BOOTSTRAP_LUA = r"""
return function(bridge)
    local b_get_time = bridge.get_time
    local b_get_server_time = bridge.get_server_time
    local b_is_valid_event = bridge.is_valid_event
    local b_resolve_c_member = bridge.resolve_c_member
    local b_resolve_global = bridge.resolve_global
    local b_resolve_enum = bridge.resolve_enum
    local b_resolve_constants = bridge.resolve_constants
    local b_is_valid_template = bridge.is_valid_template
    local b_has_widget_method = bridge.has_widget_method
    local b_record_error = bridge.record_error

    local function bridge_time()
        if b_get_time then return b_get_time() end
        return 0
    end
    local function bridge_server_time()
        if b_get_server_time then return b_get_server_time() end
        return 0
    end
    local function bridge_valid_event(name)
        if b_is_valid_event then return b_is_valid_event(name) end
        return false
    end
    local function bridge_valid_template(name)
        if b_is_valid_template then return b_is_valid_template(name) end
        return false
    end
    local function bridge_has_method(widget_type, method_name)
        if b_has_widget_method then
            return b_has_widget_method(widget_type, method_name)
        end
        return false
    end
    local function bridge_record(message, stack)
        if b_record_error then b_record_error(message, stack) end
    end

    local raw_debugstack = rawget(_G, "debugstack")
    local function safe_debugstack()
        if type(raw_debugstack) == "function" then
            local ok, stack = pcall(raw_debugstack, 2)
            if ok and type(stack) == "string" then return stack end
        end
        return ""
    end

    local allowed_nil_globals = {}
    local custom_error_handler = nil

    local function call_protected(fn, ...)
        local args = { ... }
        local arg_count = select("#", ...)
        local ok, err_obj = xpcall(function()
            return fn(unpack(args, 1, arg_count))
        end, function(err)
            return { msg = tostring(err), stack = safe_debugstack() }
        end)
        if not ok then
            local message, stack
            if type(err_obj) == "table" then
                message = tostring(err_obj.msg)
                stack = tostring(err_obj.stack or "")
            else
                message = tostring(err_obj)
                stack = ""
            end
            bridge_record(message, stack)
            if custom_error_handler then
                pcall(custom_error_handler, message .. "\n" .. stack)
            end
        end
        return ok
    end

    local function trim_string(s, chars)
        s = tostring(s)
        local first, last = 1, #s
        local function is_trimmed(char)
            if chars then
                return string.find(chars, char, 1, true) ~= nil
            end
            return string.find(char, "%s") ~= nil
        end
        while first <= last and is_trimmed(string.sub(s, first, first)) do
            first = first + 1
        end
        while last >= first and is_trimmed(string.sub(s, last, last)) do
            last = last - 1
        end
        return string.sub(s, first, last)
    end

    local function wow_strsplit(sep, s, pieces)
        s = tostring(s)
        sep = tostring(sep)
        if sep == "" then return s end
        local max_pieces = nil
        if pieces ~= nil then
            max_pieces = tonumber(pieces)
            if max_pieces and max_pieces < 1 then max_pieces = 1 end
        end
        local parts = {}
        local start = 1
        local index = 1
        while index <= #s do
            local char = string.sub(s, index, index)
            local is_sep = string.find(sep, char, 1, true) ~= nil
            if is_sep and (not max_pieces or #parts < max_pieces - 1) then
                parts[#parts + 1] = string.sub(s, start, index - 1)
                start = index + 1
            end
            index = index + 1
        end
        parts[#parts + 1] = string.sub(s, start)
        return unpack(parts)
    end

    local function wow_strjoin(delim, ...)
        local parts = {}
        local count = select("#", ...)
        for i = 1, count do
            local value = select(i, ...)
            if value == nil then
                parts[#parts + 1] = ""
            else
                parts[#parts + 1] = tostring(value)
            end
        end
        return table.concat(parts, tostring(delim))
    end

    local function wow_wipe(t)
        for key in pairs(t) do
            t[key] = nil
        end
        return t
    end

    local function bit_to_unsigned(value)
        return math.floor(tonumber(value) or 0) % 4294967296
    end
    local function bit_to_signed(value)
        local unsigned = value % 4294967296
        if unsigned >= 2147483648 then
            return unsigned - 4294967296
        end
        return unsigned
    end
    local function bit_combine(mode, first, ...)
        local result = bit_to_unsigned(first)
        local count = select("#", ...)
        for arg_index = 1, count do
            local other = bit_to_unsigned(select(arg_index, ...))
            local combined, place = 0, 1
            local left, right = result, other
            for _ = 1, 32 do
                local left_bit = left % 2
                local right_bit = right % 2
                local keep = false
                if mode == "band" then
                    keep = left_bit == 1 and right_bit == 1
                elseif mode == "bor" then
                    keep = left_bit == 1 or right_bit == 1
                else
                    keep = left_bit ~= right_bit
                end
                if keep then combined = combined + place end
                left = math.floor(left / 2)
                right = math.floor(right / 2)
                place = place * 2
            end
            result = combined
        end
        return bit_to_signed(result)
    end

    local bit_library = {}
    function bit_library.band(first, ...)
        return bit_combine("band", first, ...)
    end
    function bit_library.bor(first, ...)
        return bit_combine("bor", first, ...)
    end
    function bit_library.bxor(first, ...)
        return bit_combine("bxor", first, ...)
    end
    function bit_library.bnot(value)
        return bit_to_signed(4294967295 - bit_to_unsigned(value))
    end
    function bit_library.lshift(value, shift)
        local amount = math.floor(tonumber(shift) or 0) % 32
        local shifted = bit_to_unsigned(value) * (2 ^ amount)
        return bit_to_signed(shifted)
    end
    function bit_library.rshift(value, shift)
        local amount = math.floor(tonumber(shift) or 0) % 32
        local shifted = math.floor(bit_to_unsigned(value) / (2 ^ amount))
        return bit_to_signed(shifted)
    end
    function bit_library.arshift(value, shift)
        local amount = math.floor(tonumber(shift) or 0) % 32
        local signed = bit_to_signed(bit_to_unsigned(value))
        return math.floor(signed / (2 ^ amount))
    end

    local function wow_mixin(object, ...)
        local count = select("#", ...)
        for i = 1, count do
            local mixin = select(i, ...)
            if type(mixin) == "table" then
                for key, value in pairs(mixin) do
                    object[key] = value
                end
            end
        end
        return object
    end

    rawset(_G, "format", string.format)
    rawset(_G, "strfind", string.find)
    rawset(_G, "strmatch", string.match)
    rawset(_G, "strsub", string.sub)
    rawset(_G, "strlen", string.len)
    rawset(_G, "strlower", string.lower)
    rawset(_G, "strupper", string.upper)
    rawset(_G, "strrep", string.rep)
    rawset(_G, "strbyte", string.byte)
    rawset(_G, "strchar", string.char)
    rawset(_G, "gsub", string.gsub)
    rawset(_G, "tinsert", table.insert)
    rawset(_G, "tremove", table.remove)
    rawset(_G, "sort", table.sort)
    rawset(_G, "concat", table.concat)
    rawset(_G, "wipe", wow_wipe)
    rawset(_G, "strtrim", trim_string)
    rawset(_G, "strsplit", wow_strsplit)
    rawset(_G, "strjoin", wow_strjoin)
    rawset(_G, "bit", bit_library)
    rawset(_G, "Mixin", wow_mixin)
    rawset(_G, "CreateFromMixins", function(...)
        return wow_mixin({}, ...)
    end)
    rawset(_G, "issecretvalue", function(value)
        -- [2026-11-11 T-034] A secret is a table marked at creation. rawget avoids
        -- any metamethod, so the test itself cannot raise the secret-value error.
        return type(value) == "table" and rawget(value, "__forge_secret") == true
    end)
    rawset(_G, "GetTime", function() return bridge_time() end)
    rawset(_G, "GetServerTime", function() return bridge_server_time() end)

    local original_time = rawget(_G, "time")
    if type(original_time) ~= "function" then
        local os_table = rawget(_G, "os")
        if type(os_table) == "table" then
            original_time = os_table.time
        end
    end
    rawset(_G, "time", function(tbl)
        if tbl == nil then
            return bridge_server_time()
        end
        if type(original_time) == "function" then
            return original_time(tbl)
        end
        return bridge_server_time()
    end)

    rawset(_G, "SlashCmdList", {})
    rawset(_G, "hash_SlashCmdList", {})
    rawset(_G, "UISpecialFrames", {})

    rawset(_G, "seterrorhandler", function(fn)
        if fn == nil or type(fn) == "function" then
            custom_error_handler = fn
        end
        return custom_error_handler
    end)
    rawset(_G, "geterrorhandler", function()
        if custom_error_handler then
            return custom_error_handler
        end
        return function(err)
            bridge_record(tostring(err), "")
        end
    end)

    local created_frames = {}
    local event_registry = {}
    local frame_states = setmetatable({}, { __mode = "k" })
    local chat_messages = {}

    local frame_types = {
        Frame = true, Button = true, CheckButton = true, EditBox = true,
        ScrollFrame = true, StatusBar = true, Slider = true,
        ScrollingMessageFrame = true, MessageFrame = true,
        SimpleHTML = true, GameTooltip = true, Model = true,
        PlayerModel = true, DressUpModel = true, TabardModel = true,
        MovieFrame = true, ColorSelect = true, Minimap = true,
    }

    local function is_region_type(object_type)
        return object_type == "FontString" or object_type == "Texture"
    end

    local function remove_from(list, item)
        for i = #list, 1, -1 do
            if list[i] == item then
                table.remove(list, i)
            end
        end
    end

    local function detach_from_parent(child, state)
        local parent = state.parent
        if parent ~= nil then
            local parent_state = frame_states[parent]
            if parent_state then
                remove_from(parent_state.children, child)
                remove_from(parent_state.regions, child)
            end
            state.parent = nil
        end
    end

    local function attach_to_parent(child, state, parent)
        detach_from_parent(child, state)
        state.parent = parent
        if parent ~= nil then
            local parent_state = frame_states[parent]
            if parent_state then
                local list = parent_state.children
                if is_region_type(state.object_type) then
                    list = parent_state.regions
                end
                list[#list + 1] = child
            end
        end
    end

    local common_methods = {}
    local frame_methods = {}
    local fontstring_methods = {}
    local texture_methods = {}
    local new_widget = nil

    local widget_metatable = {
        __index = function(self, key)
            local state = frame_states[self]
            if not state then return nil end
            local method = common_methods[key]
            if method ~= nil then return method end
            if frame_types[state.object_type] then
                method = frame_methods[key]
                if method ~= nil then return method end
            end
            if state.object_type == "FontString" then
                method = fontstring_methods[key]
                if method ~= nil then return method end
            end
            if state.object_type == "Texture" then
                method = texture_methods[key]
                if method ~= nil then return method end
            end
            if type(key) == "string"
                and bridge_has_method(state.object_type, key) then
                return function() end
            end
            return nil
        end,
    }

    new_widget = function(object_type, name, parent, id)
        local frame = {}
        local state = {
            object_type = object_type, name = name, parent = nil,
            children = {}, regions = {}, shown = true, scripts = {},
            events = {}, width = 0, height = 0, alpha = 1,
            strata = "MEDIUM", level = 1, points = {}, text = "",
            id = id or 0, mouse_enabled = false, movable = false,
            clamped = false, enabled = true, texture = nil, atlas = nil,
        }
        frame_states[frame] = state
        setmetatable(frame, widget_metatable)
        if parent ~= nil then
            attach_to_parent(frame, state, parent)
        end
        if type(name) == "string" and name ~= "" then
            rawset(_G, name, frame)
        end
        return frame
    end

    function common_methods.GetObjectType(self)
        return frame_states[self].object_type
    end
    function common_methods.IsObjectType(self, object_type)
        local state = frame_states[self]
        if object_type == state.object_type then return true end
        if object_type == "Region" then return true end
        if object_type == "ScriptObject" then return true end
        if object_type == "Frame" then
            return frame_types[state.object_type] == true
        end
        if object_type == "LayeredRegion" then
            return is_region_type(state.object_type)
        end
        return false
    end
    function common_methods.GetName(self)
        return frame_states[self].name
    end
    function common_methods.GetID(self)
        return frame_states[self].id
    end
    function common_methods.SetID(self, value)
        frame_states[self].id = value or 0
    end
    function common_methods.GetParent(self)
        return frame_states[self].parent
    end
    function common_methods.SetParent(self, parent)
        attach_to_parent(self, frame_states[self], parent)
    end
    function common_methods.GetChildren(self)
        return unpack(frame_states[self].children)
    end
    function common_methods.GetNumChildren(self)
        return #frame_states[self].children
    end
    function common_methods.GetRegions(self)
        return unpack(frame_states[self].regions)
    end
    function common_methods.GetNumRegions(self)
        return #frame_states[self].regions
    end
    function common_methods.Show(self)
        local state = frame_states[self]
        if not state.shown then
            state.shown = true
            local handler = state.scripts.OnShow
            if handler then call_protected(handler, self) end
        end
    end
    function common_methods.Hide(self)
        local state = frame_states[self]
        if state.shown then
            state.shown = false
            local handler = state.scripts.OnHide
            if handler then call_protected(handler, self) end
        end
    end
    function common_methods.SetShown(self, shown)
        if shown then
            common_methods.Show(self)
        else
            common_methods.Hide(self)
        end
    end
    function common_methods.IsShown(self)
        return frame_states[self].shown
    end
    function common_methods.IsVisible(self)
        local current = self
        while current ~= nil do
            local state = frame_states[current]
            if not state then return true end
            if not state.shown then return false end
            current = state.parent
        end
        return true
    end
    function common_methods.SetScript(self, script_type, handler)
        frame_states[self].scripts[script_type] = handler
    end
    function common_methods.GetScript(self, script_type)
        return frame_states[self].scripts[script_type]
    end
    function common_methods.HasScript(self, script_type)
        return true
    end
    function common_methods.HookScript(self, script_type, hook)
        if type(hook) ~= "function" then return false end
        local state = frame_states[self]
        local previous = state.scripts[script_type]
        if previous then
            state.scripts[script_type] = function(...)
                previous(...)
                hook(...)
            end
        else
            state.scripts[script_type] = hook
        end
        return true
    end
    function common_methods.SetSize(self, width, height)
        local state = frame_states[self]
        state.width = tonumber(width) or 0
        state.height = tonumber(height) or 0
    end
    function common_methods.GetSize(self)
        local state = frame_states[self]
        return state.width, state.height
    end
    function common_methods.SetWidth(self, width)
        frame_states[self].width = tonumber(width) or 0
    end
    function common_methods.GetWidth(self)
        return frame_states[self].width
    end
    function common_methods.SetHeight(self, height)
        frame_states[self].height = tonumber(height) or 0
    end
    function common_methods.GetHeight(self)
        return frame_states[self].height
    end
    function common_methods.SetPoint(self, ...)
        local state = frame_states[self]
        local point = { ... }
        for i = 1, #state.points do
            if state.points[i][1] == point[1] then
                state.points[i] = point
                return
            end
        end
        state.points[#state.points + 1] = point
    end
    function common_methods.ClearAllPoints(self)
        frame_states[self].points = {}
    end
    function common_methods.SetAllPoints(self, target)
        local state = frame_states[self]
        if target == nil then target = state.parent end
        state.points = {
            { "TOPLEFT", target, "TOPLEFT", 0, 0 },
            { "BOTTOMRIGHT", target, "BOTTOMRIGHT", 0, 0 },
        }
    end
    function common_methods.GetNumPoints(self)
        return #frame_states[self].points
    end
    function common_methods.GetPoint(self, index)
        local point = frame_states[self].points[index or 1]
        if not point then return nil end
        return unpack(point)
    end
    function common_methods.SetAlpha(self, alpha)
        frame_states[self].alpha = tonumber(alpha) or 1
    end
    function common_methods.GetAlpha(self)
        return frame_states[self].alpha
    end
    function common_methods.EnableMouse(self, enabled)
        if enabled == nil then enabled = true end
        frame_states[self].mouse_enabled = enabled and true or false
    end
    function common_methods.IsMouseEnabled(self)
        return frame_states[self].mouse_enabled
    end
    function common_methods.SetMovable(self, movable)
        frame_states[self].movable = movable and true or false
    end
    function common_methods.IsMovable(self)
        return frame_states[self].movable
    end
    function common_methods.RegisterForDrag(self, ...)
        frame_states[self].drag_buttons = { ... }
    end
    function common_methods.StartMoving(self)
    end
    function common_methods.StopMovingOrSizing(self)
    end
    function common_methods.SetClampedToScreen(self, clamped)
        frame_states[self].clamped = clamped and true or false
    end
    function common_methods.SetFrameStrata(self, strata)
        frame_states[self].strata = tostring(strata)
    end
    function common_methods.GetFrameStrata(self)
        return frame_states[self].strata
    end
    function common_methods.SetFrameLevel(self, level)
        frame_states[self].level = tonumber(level) or 1
    end
    function common_methods.GetFrameLevel(self)
        return frame_states[self].level
    end
    function common_methods.SetText(self, text)
        if text == nil then
            frame_states[self].text = ""
        else
            frame_states[self].text = tostring(text)
        end
    end
    function common_methods.GetText(self)
        return frame_states[self].text
    end
    function common_methods.SetBackdrop(self, backdrop)
        frame_states[self].backdrop = backdrop
    end
    function common_methods.SetNormalFontObject(self, font)
        frame_states[self].normal_font = font
    end
    function common_methods.SetHighlightFontObject(self, font)
        frame_states[self].highlight_font = font
    end
    function common_methods.SetDisabledFontObject(self, font)
        frame_states[self].disabled_font = font
    end
    function common_methods.Enable(self)
        frame_states[self].enabled = true
    end
    function common_methods.Disable(self)
        frame_states[self].enabled = false
    end
    function common_methods.IsEnabled(self)
        return frame_states[self].enabled
    end

    local function check_event_name(event_name, who)
        if type(event_name) ~= "string"
            or not bridge_valid_event(event_name) then
            error(who .. ": unknown event '" .. tostring(event_name) .. "'", 3)
        end
    end

    function frame_methods.RegisterEvent(self, event_name)
        check_event_name(event_name, "RegisterEvent")
        local state = frame_states[self]
        if not state.events[event_name] then
            state.events[event_name] = true
            local list = event_registry[event_name]
            if not list then
                list = {}
                event_registry[event_name] = list
            end
            list[#list + 1] = self
        end
        return true
    end
    function frame_methods.UnregisterEvent(self, event_name)
        check_event_name(event_name, "UnregisterEvent")
        local state = frame_states[self]
        state.events[event_name] = nil
        local list = event_registry[event_name]
        if list then remove_from(list, self) end
    end
    function frame_methods.UnregisterAllEvents(self)
        local state = frame_states[self]
        for event_name in pairs(state.events) do
            local list = event_registry[event_name]
            if list then remove_from(list, self) end
        end
        state.events = {}
    end
    function frame_methods.IsEventRegistered(self, event_name)
        return frame_states[self].events[event_name] == true
    end
    function frame_methods.CreateFontString(self, name, layer, inherits)
        local region = new_widget("FontString", name, self)
        local state = frame_states[region]
        state.layer = layer
        state.inherits = inherits
        return region
    end
    function frame_methods.CreateTexture(self, name, layer, inherits)
        local region = new_widget("Texture", name, self)
        local state = frame_states[region]
        state.layer = layer
        state.inherits = inherits
        return region
    end

    function fontstring_methods.SetTextColor(self, ...)
        frame_states[self].text_color = { ... }
    end
    function fontstring_methods.SetFontObject(self, font)
        frame_states[self].font_object = font
    end
    function fontstring_methods.SetJustifyH(self, justify)
        frame_states[self].justify_h = justify
    end
    function fontstring_methods.SetJustifyV(self, justify)
        frame_states[self].justify_v = justify
    end

    function texture_methods.SetTexture(self, texture)
        frame_states[self].texture = texture
    end
    function texture_methods.GetTexture(self)
        return frame_states[self].texture
    end
    function texture_methods.SetColorTexture(self, ...)
        frame_states[self].color_texture = { ... }
    end
    function texture_methods.SetVertexColor(self, ...)
        frame_states[self].vertex_color = { ... }
    end
    function texture_methods.SetTexCoord(self, ...)
        frame_states[self].tex_coord = { ... }
    end
    function texture_methods.SetAtlas(self, atlas)
        frame_states[self].atlas = atlas
    end

    local function create_frame(frame_type, name, parent, template, id)
        frame_type = frame_type or "Frame"
        if type(template) == "string" and template ~= "" then
            for piece in string.gmatch(template, "[^,]+") do
                local tmpl = trim_string(piece)
                if tmpl ~= "" and not bridge_valid_template(tmpl) then
                    error("CreateFrame: unknown template '" .. tmpl .. "'", 2)
                end
            end
        end
        local frame = new_widget(tostring(frame_type), name, parent, id)
        created_frames[#created_frames + 1] = frame
        return frame
    end
    rawset(_G, "CreateFrame", create_frame)

    create_frame("Frame", "UIParent")
    local chat_frame = create_frame(
        "ScrollingMessageFrame", "DEFAULT_CHAT_FRAME")
    rawset(chat_frame, "messages", chat_messages)
    rawset(chat_frame, "AddMessage", function(self, message)
        chat_messages[#chat_messages + 1] = tostring(message)
    end)

    local controller = {}
    controller.call_protected = call_protected
    controller.created_frames = created_frames
    controller.chat_messages = chat_messages

    function controller.fire_event(event_name, ...)
        local registered = event_registry[event_name]
        if not registered then return end
        local snapshot = {}
        for i = 1, #registered do
            snapshot[i] = registered[i]
        end
        for i = 1, #snapshot do
            local frame = snapshot[i]
            local state = frame_states[frame]
            if state and state.events[event_name] then
                local handler = state.scripts.OnEvent
                if handler then
                    call_protected(handler, frame, event_name, ...)
                end
            end
        end
    end

    local function slash_handler_for(key)
        local slash_list = rawget(_G, "SlashCmdList")
        if type(slash_list) ~= "table" then return nil end
        return rawget(slash_list, key)
    end

    local function collect_slash_entries()
        local entries = {}
        for raw_key in pairs(_G) do
            if type(raw_key) == "string" then
                local name = string.match(raw_key, "^SLASH_(.+)%d+$")
                if name then
                    local command = rawget(_G, raw_key)
                    if type(command) == "string" then
                        entries[#entries + 1] = {
                            key = name, command = command,
                        }
                    end
                end
            end
        end
        return entries
    end

    function controller.run_slash(text)
        if type(text) ~= "string" then return false end
        local cmd, msg = string.match(text, "^%s*(/%S+)%s*(.*)$")
        if not cmd then return false end
        msg = msg or ""
        local wanted = string.lower(cmd)
        local entries = collect_slash_entries()
        for i = 1, #entries do
            local entry = entries[i]
            if string.lower(entry.command) == wanted then
                local handler = slash_handler_for(entry.key)
                if type(handler) == "function" then
                    call_protected(handler, msg, nil)
                    return true
                end
            end
        end
        return false
    end

    function controller.list_slash_commands()
        local seen = {}
        local commands = {}
        local entries = collect_slash_entries()
        for i = 1, #entries do
            local entry = entries[i]
            local handler = slash_handler_for(entry.key)
            if type(handler) == "function"
                and not seen[entry.command] then
                seen[entry.command] = true
                commands[#commands + 1] = entry.command
            end
        end
        table.sort(commands)
        return commands
    end

    function controller.allow_nil_global(name)
        allowed_nil_globals[name] = true
    end

    -- [2026-11-11 T-007] Python callables arrive in lupa as callable userdata (`type(x) ==
    -- "userdata"`). Addon code and ForgeProbe inspect `type(fn) == "function"`, so every
    -- Python callback exposed as a WoW API function is wrapped in a thin Lua closure.
    local function wrap_callable(value)
        if value == nil or type(value) == "function" or type(value) == "table"
            or type(value) == "string" or type(value) == "number"
            or type(value) == "boolean" then
            return value
        end
        return function(...) return value(...) end
    end

    function controller.set_global_function(name, fn)
        rawset(_G, name, wrap_callable(fn))
    end

    function controller.install_namespace(ns_name, methods_table)
        local ns = {}
        if methods_table ~= nil then
            for key, value in pairs(methods_table) do
                rawset(ns, key, wrap_callable(value))
            end
        end
        setmetatable(ns, {
            __index = function(t, key)
                local resolved = nil
                if b_resolve_c_member then
                    resolved = b_resolve_c_member(ns_name, key)
                end
                if resolved ~= nil then
                    local wrapped = wrap_callable(resolved)
                    rawset(t, key, wrapped)
                    return wrapped
                end
                error("unknown API member: " .. ns_name .. "."
                    .. tostring(key), 2)
            end,
        })
        rawset(_G, ns_name, ns)
        return ns
    end

    function controller.arm_strict_globals()
        local function strict_lookup(resolver, label)
            return setmetatable({}, {
                __index = function(t, key)
                    local resolved = nil
                    if resolver then resolved = resolver(key) end
                    if resolved ~= nil then
                        rawset(t, key, resolved)
                        return resolved
                    end
                    error("unknown " .. label .. ": "
                        .. tostring(key), 2)
                end,
            })
        end
        rawset(_G, "Enum", strict_lookup(b_resolve_enum, "Enum"))
        rawset(_G, "Constants",
            strict_lookup(b_resolve_constants, "Constants"))
        setmetatable(_G, {
            __index = function(t, key)
                -- [2026-11-11 T-007] lupa's C call wrapper executes an unprotected
                -- `lua_getglobal(L, "debug")` before entering `lua_pcall`. Raising
                -- inside an unprotected C API lookup triggers a Lua C panic (`abort`),
                -- whereas every real Lua `GETGLOBAL` has a non-[C] Lua caller frame
                -- at level 3 of `debugstack("", 3)` (level 1 is `debugstack` itself,
                -- level 2 is `__index`, level 3 is `__index`'s caller).
                if type(raw_debugstack) == "function" then
                    local trace = raw_debugstack("", 3) or ""
                    if trace == "\nstack traceback:"
                        or string.sub(trace, 1, 22) == "\nstack traceback:\n\t[C]" then
                        return nil
                    end
                end
                local found, value = false, nil
                if b_resolve_global then
                    found, value = b_resolve_global(key)
                end
                if found then
                    local wrapped = wrap_callable(value)
                    if wrapped ~= nil then rawset(t, key, wrapped) end
                    return wrapped
                end
                if allowed_nil_globals[key] then return nil end
                error("unknown global: " .. tostring(key), 2)
            end,
        })
    end

    function controller.raw_get_global(name)
        return rawget(_G, name)
    end

    function controller.raw_set_global(name, value)
        rawset(_G, name, value)
    end

    function controller.run_addon_chunk(source, chunk_name, addon_name, ns_table)
        local compiled, err = loadstring(source, "@" .. tostring(chunk_name))
        if not compiled then
            local msg = "compile: " .. tostring(err)
            bridge_record(msg, "")
            if custom_error_handler then
                pcall(custom_error_handler, msg)
            end
            return false
        end
        return call_protected(compiled, addon_name, ns_table)
    end

    function controller.make_secret()
        -- [2026-11-11 T-034] Opaque while a restriction is active. Arithmetic,
        -- relational comparison and concatenation error. A widget setter may
        -- hold the value: tostring of a table does not call those metamethods.
        -- Cross-type == stays Lua 5.1's false, pinned in goose-deuce.md.
        local function reject(kind)
            error("secret-value: " .. kind, 2)
        end
        local secret = { __forge_secret = true }
        return setmetatable(secret, {
            __add = function() reject("arithmetic") end,
            __sub = function() reject("arithmetic") end,
            __mul = function() reject("arithmetic") end,
            __div = function() reject("arithmetic") end,
            __mod = function() reject("arithmetic") end,
            __pow = function() reject("arithmetic") end,
            __unm = function() reject("arithmetic") end,
            __concat = function() reject("concatenation") end,
            __lt = function() reject("comparison") end,
            __le = function() reject("comparison") end,
        })
    end

    return controller
end
"""


def install_bootstrap(runtime: Any, bridge: Any) -> Any:
    """Install the WoW Lua environment into ``runtime`` and return its controller.

    Why this exists:
        Every headless client must cross the same seam: run the bootstrap chunk to get
        the installer, then call it with the Python bridge. Doing both in one place
        keeps callers from depending on how the chunk is shaped.

    Args:
        runtime: A sandboxed ``lupa.lua51`` runtime (from ``luavm.new_runtime``).
        bridge: A table or mapping of Python callbacks the bootstrap resolves facts
            through: ``get_time``, ``get_server_time``, ``is_valid_event``,
            ``resolve_c_member``, ``resolve_global``, ``resolve_enum``,
            ``resolve_constants``, ``is_valid_template``, ``has_widget_method`` and
            ``record_error``.

    Returns:
        The Lua ``controller`` table the installer returns, exposing
        ``call_protected``, ``fire_event``, ``run_slash``,
        ``list_slash_commands``, ``allow_nil_global``, ``install_namespace``,
        ``arm_strict_globals``, ``raw_get_global`` and ``raw_set_global``.

    Failure modes:
        Raises whatever ``runtime.execute`` or the installer raises when the bootstrap
        cannot run (for example a bridge that is neither a Lua table nor a mapping the
        runtime can index); no error type is translated here.
    """
    installer = runtime.execute(BOOTSTRAP_LUA)
    return installer(bridge)
