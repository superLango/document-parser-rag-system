(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc nav a'));
  if (!links.length || !('IntersectionObserver' in window)) return;

  var sectionMap = {};
  var sections = [];

  links.forEach(function (link) {
    var href = link.getAttribute('href');
    if (!href || href.charAt(0) !== '#') return;
    var el = document.querySelector(href);
    if (!el) return;
    sectionMap[el.id] = link;
    sections.push(el);
  });

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      links.forEach(function (link) { link.classList.remove('active'); });
      var active = sectionMap[entry.target.id];
      if (active) active.classList.add('active');
    });
  }, {
    rootMargin: '-18% 0px -68% 0px',
    threshold: 0
  });

  sections.forEach(function (section) { observer.observe(section); });
})();
