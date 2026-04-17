/**
 * On iPad only: replaces native <select> with a custom listbox UI (avoids iOS/iPad native picker animation).
 * Elsewhere: native selects stay visible; no wrapper (avoids flicker on desktop and iPhone).
 * Keeps the real <select> in the DOM for forms, .value, and change listeners when enhanced.
 */
(function () {
  'use strict';

  var openInstance = null;

  function isIPad() {
    if (typeof navigator === 'undefined') return false;
    if (/iPad/.test(navigator.userAgent || '')) return true;
    // iPadOS 13+ Safari often reports as desktop Mac with touch.
    return navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  }

  function variantFor(select) {
    if (select.classList.contains('filter-select')) return 'filter';
    if (select.classList.contains('cell-select')) return 'cell';
    if (select.closest('.form-group')) return 'form';
    return 'filter';
  }

  /** Type / category filters: grow menu to full list height when it fits the viewport */
  function wantsExpandTypeList(sel) {
    var n = sel.name || '';
    return n === 'tune_type' || n === 'type' || n === 'set_type';
  }

  function enhanceSelect(select) {
    if (!select || select.multiple || select.closest('.mp-dd')) return;
    if (select.hasAttribute('data-mp-dd-skip')) return;

    var parent = select.parentNode;
    var wrapper = document.createElement('div');
    wrapper.className = 'mp-dd mp-dd--' + variantFor(select);

    parent.insertBefore(wrapper, select);
    wrapper.appendChild(select);

    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'mp-dd-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');

    var listBase = 'mp-dd-lst-' + (select.id || ('noid-' + Math.random().toString(36).slice(2, 9)));
    var menuId = listBase;
    trigger.setAttribute('aria-controls', menuId);

    var al = select.getAttribute('aria-label');
    var lb = select.getAttribute('aria-labelledby');
    if (al) trigger.setAttribute('aria-label', al);
    if (lb) trigger.setAttribute('aria-labelledby', lb);

    var labelSpan = document.createElement('span');
    labelSpan.className = 'mp-dd-label';
    trigger.appendChild(labelSpan);

    var menu = document.createElement('ul');
    menu.className = 'mp-dd-menu';
    menu.id = menuId;
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;

    wrapper.insertBefore(trigger, select);
    wrapper.insertBefore(menu, select);

    select.classList.add('mp-dd-native');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;

    if (select.id) {
      trigger.id = select.id + '__mpdd';
      var esc = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(select.id) : select.id.replace(/"/g, '\\"');
      var lab = document.querySelector('label[for="' + esc + '"]');
      if (lab) lab.htmlFor = trigger.id;
    }

    var open = false;
    var activeIdx = -1;

    function syncLabel() {
      var opt = select.selectedOptions[0];
      labelSpan.textContent = opt ? opt.textContent : '';
    }

    function optionNodes() {
      return Array.prototype.slice.call(menu.querySelectorAll('.mp-dd-option:not(.mp-dd-option--disabled)'));
    }

    function rebuildMenu() {
      menu.replaceChildren();
      var opts = select.querySelectorAll('option');
      for (var i = 0; i < opts.length; i++) {
        var opt = opts[i];
        var li = document.createElement('li');
        li.className = 'mp-dd-option';
        li.setAttribute('role', 'option');
        li.dataset.value = opt.value;
        li.textContent = opt.textContent;
        li.id = menuId + '-o-' + i;
        if (opt.selected) {
          li.setAttribute('aria-selected', 'true');
          li.classList.add('mp-dd-option--selected');
        } else {
          li.setAttribute('aria-selected', 'false');
        }
        if (opt.disabled) {
          li.classList.add('mp-dd-option--disabled');
          li.setAttribute('aria-disabled', 'true');
        }
        menu.appendChild(li);
      }
    }

    function positionMenu() {
      var rect = trigger.getBoundingClientRect();
      var vw = window.innerWidth;
      var vh = window.innerHeight;
      menu.style.position = 'fixed';
      var left = Math.max(8, Math.min(rect.left, vw - 8));
      menu.style.left = left + 'px';
      menu.style.minWidth = Math.max(rect.width, 120) + 'px';
      menu.style.width = 'max-content';
      menu.style.maxWidth = Math.max(120, vw - 16) + 'px';
      menu.style.zIndex = '600';

      var spaceBelow = vh - rect.bottom - 8;
      var spaceAbove = rect.top - 8;
      var expandType = wantsExpandTypeList(select);

      menu.style.maxHeight = 'none';
      menu.style.overflowY = 'hidden';
      var naturalH = menu.scrollHeight;

      function placeBelow() {
        menu.style.top = (rect.bottom + 2) + 'px';
        menu.style.bottom = '';
      }
      function placeAbove() {
        menu.style.top = '';
        menu.style.bottom = (vh - rect.top + 2) + 'px';
      }

      if (expandType && naturalH > 0) {
        if (naturalH <= spaceBelow) {
          menu.style.maxHeight = naturalH + 'px';
          menu.style.overflowY = 'hidden';
          placeBelow();
        } else if (naturalH <= spaceAbove) {
          menu.style.maxHeight = naturalH + 'px';
          menu.style.overflowY = 'hidden';
          placeAbove();
        } else if (spaceBelow >= spaceAbove) {
          menu.style.maxHeight = spaceBelow + 'px';
          menu.style.overflowY = 'auto';
          placeBelow();
        } else {
          menu.style.maxHeight = spaceAbove + 'px';
          menu.style.overflowY = 'auto';
          placeAbove();
        }
      } else {
        var maxH = Math.min(280, Math.max(spaceBelow, spaceAbove, 120));
        menu.style.maxHeight = maxH + 'px';
        menu.style.overflowY = 'auto';
        var mh = menu.offsetHeight || Math.min(maxH, menu.scrollHeight);
        if (mh <= spaceBelow - 2 || spaceBelow >= spaceAbove) {
          menu.style.top = (rect.bottom + 2) + 'px';
          menu.style.bottom = '';
        } else {
          menu.style.top = '';
          menu.style.bottom = (vh - rect.top + 2) + 'px';
        }
      }
    }

    function setActive(idx) {
      var nodes = optionNodes();
      if (!nodes.length) return;
      activeIdx = Math.max(0, Math.min(idx, nodes.length - 1));
      nodes.forEach(function (n, j) {
        n.classList.toggle('mp-dd-option--active', j === activeIdx);
      });
      var el = nodes[activeIdx];
      if (el) {
        el.scrollIntoView({ block: 'nearest' });
        trigger.setAttribute('aria-activedescendant', el.id);
      } else {
        trigger.removeAttribute('aria-activedescendant');
      }
    }

    function close() {
      if (!open) return;
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      open = false;
      activeIdx = -1;
      trigger.removeAttribute('aria-activedescendant');
      menu.querySelectorAll('.mp-dd-option--active').forEach(function (n) {
        n.classList.remove('mp-dd-option--active');
      });
      window.removeEventListener('scroll', onReposition, true);
      window.removeEventListener('resize', onReposition);
      document.removeEventListener('mousedown', onDocDown, true);
      document.removeEventListener('keydown', onDocKey, true);
      if (openInstance === instance) openInstance = null;
    }

    function commitFromActive() {
      var nodes = optionNodes();
      if (activeIdx < 0 || activeIdx >= nodes.length) return;
      var v = nodes[activeIdx].dataset.value;
      if (select.value !== v) {
        select.value = v;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      syncLabel();
      close();
      trigger.focus();
    }

    function openMenu() {
      if (open) return;
      if (openInstance && openInstance !== instance) openInstance.close();
      rebuildMenu();
      menu.hidden = false;
      menu.style.visibility = 'hidden';
      positionMenu();
      menu.style.visibility = '';
      trigger.setAttribute('aria-expanded', 'true');
      open = true;
      openInstance = instance;
      var selI = -1;
      var nodes = optionNodes();
      for (var j = 0; j < nodes.length; j++) {
        if (nodes[j].classList.contains('mp-dd-option--selected')) {
          selI = j;
          break;
        }
      }
      setActive(selI >= 0 ? selI : 0);
      window.addEventListener('scroll', onReposition, true);
      window.addEventListener('resize', onReposition);
      document.addEventListener('mousedown', onDocDown, true);
      document.addEventListener('keydown', onDocKey, true);
    }

    function onReposition() {
      if (open) positionMenu();
    }

    function onDocDown(e) {
      if (!wrapper.contains(e.target)) close();
    }

    function onDocKey(e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
        trigger.focus();
        return;
      }
      if (!open) return;
      var nodes = optionNodes();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (activeIdx < 0) setActive(0);
        else setActive(activeIdx + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (activeIdx < 0) setActive(nodes.length - 1);
        else setActive(activeIdx - 1);
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        commitFromActive();
      } else if (e.key === 'Home') {
        e.preventDefault();
        setActive(0);
      } else if (e.key === 'End') {
        e.preventDefault();
        setActive(nodes.length - 1);
      }
    }

    menu.addEventListener('mousedown', function (e) {
      e.preventDefault();
    });

    menu.addEventListener('mouseover', function (e) {
      var li = e.target.closest('.mp-dd-option');
      if (!li || li.classList.contains('mp-dd-option--disabled')) return;
      var nodes = optionNodes();
      var idx = nodes.indexOf(li);
      if (idx >= 0 && idx !== activeIdx) setActive(idx);
    });

    menu.addEventListener('click', function (e) {
      var li = e.target.closest('.mp-dd-option');
      if (!li || li.classList.contains('mp-dd-option--disabled')) return;
      var v = li.dataset.value;
      if (select.value !== v) {
        select.value = v;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      syncLabel();
      close();
      trigger.focus();
    });

    trigger.addEventListener('click', function (e) {
      e.preventDefault();
      if (open) close();
      else openMenu();
    });

    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!open) openMenu();
        else if (e.key === 'ArrowDown') setActive(activeIdx + 1);
        else setActive(activeIdx - 1);
      }
    });

    var mo = new MutationObserver(function () {
      syncLabel();
      if (open) {
        rebuildMenu();
        positionMenu();
      }
    });
    mo.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'selected'] });

    select.addEventListener('change', syncLabel);

    var instance = {
      wrapper: wrapper,
      close: close,
      sync: syncLabel,
    };

    wrapper._mpDdInstance = instance;
    syncLabel();

    return instance;
  }

  function enhanceIn(root) {
    if (!root || !isIPad()) return;
    var sel = root.querySelectorAll(
      'select.filter-select, select.cell-select, .form-group select:not(.mp-dd-native)'
    );
    for (var i = 0; i < sel.length; i++) {
      enhanceSelect(sel[i]);
    }
  }

  function refresh(select) {
    if (!select) return;
    var w = select.closest('.mp-dd');
    if (w && w._mpDdInstance) w._mpDdInstance.sync();
  }

  window.mpEnhanceCustomSelectsIn = enhanceIn;
  window.mpRefreshCustomSelect = refresh;

  function runEnhance() {
    try {
      enhanceIn(document);
    } finally {
      document.documentElement.classList.remove('mp-selects-pending');
    }
  }
  // Run as soon as this deferred script executes (document is parsed) so native
  // <select> elements are replaced before first paint, avoiding toolbar flicker.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runEnhance);
  } else {
    runEnhance();
  }
})();
