-- Board tab for Guildhall (created 2026-11-11).
-- Purpose: the window's board tab. It turns Guildhall.Board.rows() into one
-- "author: text" line per visible post, pins marked, and draws the first eight
-- as FontStrings in the tab's container (Window owns containers since T-053).
-- Invariants: loading this file creates no frames and builds nothing; the tab
-- is built the first time the window shows it, and refresh() repaints the
-- lines from the fold every time the window shows the tab again.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.BoardTab = {
    built = false,
    lines = {},
}

-- [2026-11-11 T-043] The tab shows the first eight rows: the window is a
-- overview, not a scroller, so the line list and the FontStrings stay in step.
local MAX_LINES = 8

-- [2026-11-11 T-057] The FontString pool, created once at build and repainted
-- by refresh(): the pre-T-057 build drew fresh FontStrings from a one-time
-- snapshot, so a post that arrived after first show could never appear.
local texts = {}

-- [2026-11-11 T-057] Repaint from the fold: recompute the line model, then
-- write it into the pooled FontStrings (unused slots are hidden).
local function refresh()
    local rows = ns.Board.rows()
    local lines = {}
    local shown = math.min(#rows, MAX_LINES)
    for i = 1, shown do
        local row = rows[i]
        local line = row.a .. ": " .. row.text
        if row.pinned then
            line = "[pin] " .. line
        end
        lines[#lines + 1] = line
    end
    ns.BoardTab.lines = lines
    for i = 1, MAX_LINES do
        local text = texts[i]
        if text ~= nil then
            if lines[i] ~= nil then
                text:SetText(lines[i])
                text:Show()
            else
                text:Hide()
            end
        end
    end
end

ns.BoardTab.refresh = refresh

local function build(frame)
    ns.BoardTab.built = true
    local font = (ns.Theme and ns.Theme.font) or "GameFontNormal"
    for i = 1, MAX_LINES do
        local text = frame:CreateFontString(nil, "OVERLAY", font)
        text:SetPoint("TOPLEFT", 16, -40 - (i - 1) * 14)
        texts[i] = text
    end
    -- [2026-11-11 T-057] The post box (SPEC-GUILDHALL §8.1: "a post box for
    -- those allowed"). Board.post enforces who may post, so the box is safe
    -- to show everyone: a refused post leaves the text in place and the
    -- lines unchanged, and the author sees the button do nothing rather
    -- than lose a draft. Live T-036 evidence: without this box the board
    -- could display posts but never create one in game.
    local theme = ns.Theme or {}
    local templates = theme.templates or {}
    local edit = CreateFrame("EditBox", nil, frame, "InputBoxTemplate")
    edit:SetSize(420, 24)
    edit:SetPoint("TOPLEFT", 20, -40 - MAX_LINES * 14 - 16)
    -- [2026-11-11 T-057] Guarded: not every widget surface (the headless
    -- stub included) models EditBox focus methods; losing auto-focus
    -- control must never stop the tab building.
    pcall(edit.SetAutoFocus, edit, false)
    local post = CreateFrame("Button", nil, frame, templates.button or "UIPanelButtonTemplate")
    post:SetSize(90, 24)
    post:SetPoint("LEFT", edit, "RIGHT", 8, 0)
    post:SetText("Post")
    local function submit()
        local id = ns.Board.post(edit:GetText() or "")
        if id ~= nil then
            edit:SetText("")
        end
        pcall(edit.ClearFocus, edit)
        refresh()
    end
    post:SetScript("OnClick", submit)
    edit:SetScript("OnEnterPressed", submit)
    ns.BoardTab.editbox = edit
    ns.BoardTab.post_button = post
    refresh()
end

-- [2026-11-11 T-043] Registration only: ns.Window owns the container and calls
-- build(container) the first time the tab is shown (SPEC-GUILDHALL §9).
-- [2026-11-11 T-057] The third argument is the refresh the window replays on
-- every later show, so reopening the tab is never a stale snapshot.
if type(ns.Window) == "table" and type(ns.Window.register_tab) == "function" then
    ns.Window.register_tab("board", build, refresh)
end

return ns.BoardTab
