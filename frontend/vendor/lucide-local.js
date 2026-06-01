/*
 * Local icon renderer for this application.
 * It intentionally avoids CDN/network loading and exposes the tiny subset of
 * the lucide.createIcons() API used by the frontend.
 */
(function () {
    const icons = {
        activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
        "brain-circuit": '<path d="M9 3a4 4 0 0 0-4 4v1a4 4 0 0 0-2 7 4 4 0 0 0 4 6h2"/><path d="M15 3a4 4 0 0 1 4 4v1a4 4 0 0 1 2 7 4 4 0 0 1-4 6h-2"/><path d="M9 7h6M9 12h6M9 17h6"/><circle cx="7" cy="7" r="1"/><circle cx="17" cy="12" r="1"/><circle cx="7" cy="17" r="1"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
        "cloud-lightning": '<path d="M17.5 19H7a5 5 0 1 1 1.4-9.8A7 7 0 0 1 21 12.5a4.5 4.5 0 0 1-3.5 6.5Z"/><path d="m13 11-3 5h4l-3 5"/>',
        cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M4 10h2M4 14h2M18 10h2M18 14h2M10 4v2M14 4v2M10 18v2M14 18v2"/>',
        database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
        download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
        "file-code": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="m10 13-2 2 2 2M14 17l2-2-2-2"/>',
        "file-json": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M10 13c-1 0-1.5.5-1.5 1.5v1c0 1-.5 1.5-1.5 1.5 1 0 1.5.5 1.5 1.5v1c0 1 .5 1.5 1.5 1.5M14 13c1 0 1.5.5 1.5 1.5v1c0 1 .5 1.5 1.5 1.5-1 0-1.5.5-1.5 1.5v1c0 1-.5 1.5-1.5 1.5"/>',
        "file-up": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="m9 15 3-3 3 3"/>',
        filter: '<path d="M3 5h18l-7 8v5l-4 2v-7Z"/>',
        "git-merge": '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 9v6a3 3 0 0 0 3 3h6"/><path d="M18 15V6"/>',
        grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
        hourglass: '<path d="M5 2h14M5 22h14M7 2v6l5 4-5 4v6M17 2v6l-5 4 5 4v6"/>',
        "key-round": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M11 12 21 2"/><path d="m16 7 3 3"/><path d="m14 9 3 3"/>',
        network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M12 8v4M5 16v-2a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2"/>',
        "package-open": '<path d="m3 7 9 5 9-5"/><path d="M12 22V12"/><path d="m21 7-9-5-9 5v10l9 5 9-5Z"/><path d="m3 7 9 5 9-5"/>',
        repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
        "settings-2": '<path d="M20 7h-9"/><path d="M14 17H4"/><circle cx="7" cy="7" r="3"/><circle cx="17" cy="17" r="3"/>',
        "shield-check": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/>',
        sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M2 14h4M10 8h4M18 16h4"/>',
        sparkles: '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z"/><path d="M5 3v4M3 5h4M19 17v4M17 19h4"/>',
        terminal: '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
        timer: '<path d="M10 2h4"/><path d="M12 14v-4"/><circle cx="12" cy="14" r="8"/><path d="m19 5-2 2"/>',
        "trash-2": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
        users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
        zap: '<path d="M13 2 3 14h8l-1 8 11-14h-8Z"/>'
    };

    function createSvg(name, source) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "2");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");
        svg.setAttribute("width", "24");
        svg.setAttribute("height", "24");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("data-lucide", name);
        svg.innerHTML = icons[name] || icons.file;
        svg.className = source.className || "";
        return svg;
    }

    window.lucide = {
        createIcons() {
            document.querySelectorAll("i[data-lucide]").forEach((node) => {
                const name = node.getAttribute("data-lucide");
                node.replaceWith(createSvg(name, node));
            });
        }
    };
})();
