-- Classic theme for @@ADDON@@ (created 2026-11-11).
-- Purpose: one table of colours, size, and stock frame templates.
-- Invariant: every template name here is a stock frame template, not a custom XML frame.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Theme = {
    name = "Classic",
    width = 900,
    height = 560,
    font = "GameFontNormal",
    text = { 1, 0.82, 0, 1 },
    templates = {
        frame = "BasicFrameTemplateWithInset",
        button = "UIPanelButtonTemplate",
        close = "UIPanelCloseButton",
        scroll = "UIPanelScrollFrameTemplate",
    },
}

return ns.Theme
