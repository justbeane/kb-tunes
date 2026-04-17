/**
 * Text field + filtering suggestion list (DB-driven values).
 * No row is keyboard-highlighted until ArrowDown; Enter or Tab applies the
 * highlighted row or closes the menu; mousedown on a row picks and closes.
 * Table cells: Enter blurs to commit after picking.
 */
(function () {
  'use strict';

  var activeWrap = null;

  function hideActiveMenu() {
    if (!activeWrap) return;
    var menu = activeWrap._mpMenu;
    var input = activeWrap._mpInput;
    if (menu) {
      if (activeWrap.classList.contains('mp-suggest--cell')) menu.style.cssText = '';
      menu.hidden = true;
      menu.innerHTML = '';
    }
    if (input) input.setAttribute('aria-expanded', 'false');
    activeWrap = null;
  }

  document.addEventListener(
    'mousedown',
    function (e) {
      if (!activeWrap) return;
      if (activeWrap.contains(e.target)) return;
      var closing = activeWrap;
      hideActiveMenu();
      if (!closing.classList.contains('mp-suggest--cell')) {
        var inp = closing._mpInput;
        var items = closing._mpAllItems;
        if (inp && items) {
          var next = canonicalOrEmpty(inp.value, items);
          if (next !== inp.value) {
            inp.value = next;
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
      }
    },
    true
  );

  function normalizeList(raw) {
    if (!Array.isArray(raw)) return [];
    var out = [];
    var seen = Object.create(null);
    for (var i = 0; i < raw.length; i++) {
      var s = String(raw[i]).trim();
      if (!s || seen[s]) continue;
      seen[s] = 1;
      out.push(s);
    }
    out.sort(function (a, b) {
      return a.toLowerCase().localeCompare(b.toLowerCase());
    });
    return out;
  }

  function filterItems(items, query) {
    var q = String(query || '').trim().toLowerCase();
    if (!q) return items.slice();
    return items.filter(function (x) {
      return x.toLowerCase().indexOf(q) !== -1;
    });
  }

  /** Full match against suggestion list (case-insensitive); else empty string. */
  function canonicalOrEmpty(raw, allItems) {
    var t = String(raw || '').trim();
    if (!t) return '';
    var low = t.toLowerCase();
    for (var i = 0; i < allItems.length; i++) {
      if (allItems[i].toLowerCase() === low) return allItems[i];
    }
    return '';
  }

  function mpSuggestAttach(wrap, input, menu, items) {
    var all = normalizeList(items);
    wrap._mpAllItems = all;
    var activeIdx = -1;
    var isCell = wrap.classList.contains('mp-suggest--cell');

    function endPickSkipOpen() {
      setTimeout(function () {
        wrap._mpSkipOpen = false;
        wrap._mpPickingFromMenu = false;
      }, 0);
    }
    var tableWrap = wrap.closest ? wrap.closest('.table-wrap') : null;
    var tableInner =
      tableWrap && tableWrap.querySelector(':scope > .table-wrap__inner');
    var tableScrollHost = tableInner || tableWrap;
    var CELL_MAX = 5;

    function positionCellMenu() {
      if (!isCell || menu.hidden) return;
      var r = input.getBoundingClientRect();
      var vw = window.innerWidth || document.documentElement.clientWidth;
      var pad = 8;
      var left = Math.max(pad, r.left);
      var maxW = Math.max(r.width, vw - left - pad);
      menu.style.position = 'fixed';
      menu.style.left = left + 'px';
      menu.style.top = r.bottom + 2 + 'px';
      menu.style.right = 'auto';
      menu.style.bottom = 'auto';
      menu.style.minWidth = r.width + 'px';
      menu.style.width = 'max-content';
      menu.style.maxWidth = maxW + 'px';
      menu.style.zIndex = '400';
    }

    function renderMenu() {
      var q = input.value;
      var filtered = filterItems(all, q);
      if (isCell) filtered = filtered.slice(0, CELL_MAX);
      menu.innerHTML = '';
      filtered.forEach(function (text) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.className = 'mp-suggest-item';
        li.textContent = text;
        li.dataset.value = text;
        li.addEventListener('mousedown', function (e) {
          e.preventDefault();
          wrap._mpPickingFromMenu = true;
          wrap._mpSkipOpen = true;
          input.value = text;
          hideActiveMenu();
          input.focus();
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          endPickSkipOpen();
        });
        menu.appendChild(li);
      });
      var opts = menu.querySelectorAll('li');
      activeIdx = -1;
      updateActive(opts);

      if (opts.length === 0) {
        menu.hidden = true;
        input.setAttribute('aria-expanded', 'false');
      } else {
        menu.hidden = false;
        input.setAttribute('aria-expanded', 'true');
      }
    }

    function updateActive(opts) {
      opts = opts || menu.querySelectorAll('li');
      for (var i = 0; i < opts.length; i++) {
        opts[i].classList.toggle('mp-suggest-active', i === activeIdx);
      }
    }

    if (isCell) {
      if (!window.__mpSuggestCellGlobalBound) {
        window.__mpSuggestCellGlobalBound = true;
        function closeCellMenuOnViewportChange() {
          if (activeWrap && activeWrap.classList.contains('mp-suggest--cell')) hideActiveMenu();
        }
        window.addEventListener('resize', closeCellMenuOnViewportChange);
        window.addEventListener('scroll', closeCellMenuOnViewportChange, true);
      }
      if (tableScrollHost && !tableScrollHost._mpSuggestTableScrollHook) {
        tableScrollHost._mpSuggestTableScrollHook = true;
        tableScrollHost.addEventListener(
          'scroll',
          function () {
            if (activeWrap && activeWrap.classList.contains('mp-suggest--cell')) hideActiveMenu();
          },
          { passive: true }
        );
      }
    }

    function showMenu() {
      activeWrap = wrap;
      wrap._mpInput = input;
      wrap._mpMenu = menu;
      renderMenu();
      if (isCell) positionCellMenu();
    }

    input.addEventListener('focus', function () {
      if (wrap._mpSkipOpen) return;
      showMenu();
    });

    input.addEventListener('click', function () {
      if (wrap._mpSkipOpen) return;
      showMenu();
    });

    input.addEventListener('input', function () {
      if (wrap._mpSkipOpen) return;
      if (activeWrap === wrap) {
        renderMenu();
        if (isCell) positionCellMenu();
      } else showMenu();
    });

    input.addEventListener('blur', function () {
      if (wrap._mpPickingFromMenu) return;
      if (activeWrap === wrap) hideActiveMenu();
      if (isCell) return;
      var next = canonicalOrEmpty(input.value, all);
      if (next !== input.value) {
        input.value = next;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });

    input.addEventListener('keydown', function (e) {
      var opts = menu.querySelectorAll('li');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          if (activeIdx < 0) activeIdx = 0;
          else activeIdx = Math.min(activeIdx + 1, opts.length - 1);
          updateActive(opts);
        } else {
          showMenu();
        }
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (!menu.hidden && opts.length) {
          if (activeIdx <= 0) activeIdx = -1;
          else activeIdx = activeIdx - 1;
          updateActive(opts);
        } else {
          showMenu();
        }
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        wrap._mpPickingFromMenu = !!(!menu.hidden && activeIdx >= 0 && opts[activeIdx]);
        wrap._mpSkipOpen = true;
        if (!menu.hidden && activeIdx >= 0 && opts[activeIdx]) {
          input.value = opts[activeIdx].dataset.value;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        hideActiveMenu();
        endPickSkipOpen();
        if (isCell) input.blur();
        return;
      }
      if (e.key === 'Tab') {
        if (menu.hidden) return;
        wrap._mpPickingFromMenu = !!(activeIdx >= 0 && opts[activeIdx]);
        wrap._mpSkipOpen = true;
        if (activeIdx >= 0 && opts[activeIdx]) {
          input.value = opts[activeIdx].dataset.value;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        hideActiveMenu();
        endPickSkipOpen();
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        hideActiveMenu();
        if (!isCell) {
          var escNext = canonicalOrEmpty(input.value, all);
          if (escNext !== input.value) {
            input.value = escNext;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
          }
        }
      }
    });
  }

  /**
   * @param {Element} [root]
   * @param {Object<string, string[]>} [tablePayload]  for .mp-suggest[data-suggest-key]
   */
  window.mpSuggestInitScope = function (root, tablePayload) {
    root = root || document;
    tablePayload = tablePayload || null;
    root.querySelectorAll('.mp-suggest').forEach(function (wrap) {
      if (wrap.dataset.mpSuggestBound === '1') return;
      var input = wrap.querySelector('.mp-suggest-input');
      var menu = wrap.querySelector('.mp-suggest-menu');
      if (!input || !menu) return;
      var sk = wrap.getAttribute('data-suggest-key');
      var dataEl = wrap.querySelector('.mp-suggest-data[type="application/json"]');
      if (sk && !dataEl && !tablePayload) return;
      var items = [];
      if (tablePayload && sk && Object.prototype.hasOwnProperty.call(tablePayload, sk)) {
        items = tablePayload[sk] || [];
      } else if (dataEl) {
        try {
          items = JSON.parse(dataEl.textContent || '[]');
        } catch (err) {
          items = [];
        }
      }
      mpSuggestAttach(wrap, input, menu, items);
      wrap.dataset.mpSuggestBound = '1';
    });
  };

  function runInit() {
    window.mpSuggestInitScope(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runInit);
  } else {
    runInit();
  }
})();
