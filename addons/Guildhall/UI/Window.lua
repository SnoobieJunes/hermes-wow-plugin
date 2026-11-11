-- Lazy window for Guildhall (created 2026-11-11).
-- Purpose: one movable window, built on first open, with tabs built on first show.
-- Invariant: loading this file creates no frames. Escape closes it via UISpecialFrames.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Window = {
    built = false,
    shown = false,
    tabs = {},
    built_tabs = {},
    templates_used = {},
    frame = nil,
    status = nil,
    tab_shown = nil,
}

local function frame_name()
    return (ADDON_NAME or "Addon") .. "Frame"
end

local function remember(template)
    ns.Window.templates_used[#ns.Window.templates_used + 1] = template
    return template
end

function ns.Window.register_tab(tab_id, build)
    if type(tab_id) ~= "string" or type(build) ~= "function" then
        return false
    end
    ns.Window.tabs[#ns.Window.tabs + 1] = { id = tab_id, build = build, built = false }
    return true
end

function ns.Window.refresh_status()
    if ns.Window.status == nil then
        return
    end
    local mates = 0
    if type(ns.Sync) == "table" and type(ns.Sync.peer_heads) == "table" then
        for _ in pairs(ns.Sync.peer_heads) do
            mates = mates + 1
        end
    end
    local queued = 0
    if type(ns.Sync) == "table" and type(ns.Sync.throttle) == "table" then
        queued = #ns.Sync.throttle.queue
    end
    local bridge = "off"
    if type(ns.Bridge) == "table" and type(ns.Bridge.state) == "string" then
        bridge = ns.Bridge.state
    end
    ns.Window.status:SetText(string.format("sync %d  queue %d  bridge %s", mates, queued, bridge))
end

function ns.Window.build()
    if ns.Window.built then
        return
    end
    local theme = ns.Theme
    local parent = UIParent
    local frame = CreateFrame("Frame", frame_name(), parent, remember(theme.templates.frame))
    frame:SetSize(theme.width, theme.height)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", function(self)
        self:StartMoving()
    end)
    frame:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
    end)
    local close = CreateFrame("Button", nil, frame, remember(theme.templates.close))
    close:SetPoint("TOPRIGHT", -6, -6)
    close:SetScript("OnClick", function()
        ns.Window.close()
    end)
    local scroll = CreateFrame("ScrollFrame", nil, frame, remember(theme.templates.scroll))
    scroll:SetPoint("TOPLEFT", 16, -32)
    scroll:SetPoint("BOTTOMRIGHT", -16, 28)
    local status = frame:CreateFontString(nil, "OVERLAY", theme.font)
    status:SetPoint("BOTTOMLEFT", 12, 8)
    ns.Window.frame = frame
    ns.Window.status = status
    ns.Window.scroll = scroll
    UISpecialFrames[#UISpecialFrames + 1] = frame_name()
    ns.Window.built = true
    ns.Window.refresh_status()
end

function ns.Window.open()
    if not ns.Window.built then
        ns.Window.build()
    end
    if ns.Window.frame ~= nil then
        ns.Window.frame:Show()
    end
    ns.Window.shown = true
end

function ns.Window.close()
    if ns.Window.frame ~= nil then
        ns.Window.frame:Hide()
    end
    ns.Window.shown = false
end

function ns.Window.show_tab(tab_id)
    if not ns.Window.built then
        ns.Window.build()
    end
    for i = 1, #ns.Window.tabs do
        local tab = ns.Window.tabs[i]
        if tab.id == tab_id then
            if not tab.built then
                tab.build(ns.Window.frame)
                tab.built = true
                ns.Window.built_tabs[tab_id] = true
            end
            ns.Window.tab_shown = tab_id
            return true
        end
    end
    return false
end

function ns.Window.template_list()
    return table.concat(ns.Window.templates_used, ",")
end

function ns.Window.escape_listed()
    local name = frame_name()
    for i = 1, #UISpecialFrames do
        if UISpecialFrames[i] == name then
            return true
        end
    end
    return false
end

if type(ns.Slash) == "table" and type(SlashCmdList) == "table" and ns.Slash.key ~= nil then
    local previous = SlashCmdList[ns.Slash.key]
    SlashCmdList[ns.Slash.key] = function(msg)
        if type(previous) == "function" then
            previous(msg)
        end
        ns.Window.open()
    end
end

return ns.Window
