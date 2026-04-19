// Thin helpers over motion.dev for site-wide animations.
// motion.dev exposes window.Motion = { animate, inView, stagger, ... }
// Exposed globally as window.Animations for simple consumption from app.js
// (which is loaded as a module but can still read window globals).

(function () {
  const M = window.Motion;

  /**
   * Fade + slide-in a list of elements with a staggered delay.
   * Used for new setup cards appearing.
   */
  function staggerIn(elements, options = {}) {
    if (!M || !elements || elements.length === 0) return;
    const { duration = 0.4, delayStep = 0.05, yOffset = 16 } = options;
    M.animate(
      elements,
      { opacity: [0, 1], transform: [`translateY(${yOffset}px)`, "translateY(0)"] },
      { duration, delay: M.stagger(delayStep), easing: "ease-out" }
    );
  }

  /**
   * Fade-out a list of elements (removed setups).
   */
  function fadeOut(elements, options = {}) {
    if (!M || !elements || elements.length === 0) return Promise.resolve();
    const { duration = 0.25 } = options;
    return M.animate(
      elements,
      { opacity: [1, 0], transform: ["translateY(0)", "translateY(-8px)"] },
      { duration, easing: "ease-in" }
    ).finished;
  }

  /**
   * Brief pulse on an element (e.g., when a value changes).
   */
  function pulse(el, options = {}) {
    if (!M || !el) return;
    const { duration = 0.5, scale = 1.08 } = options;
    M.animate(el, { transform: ["scale(1)", `scale(${scale})`, "scale(1)"] }, { duration, easing: "ease-out" });
  }

  /**
   * Animate a number in a text element from start to end over `duration` ms.
   * Use for PnL, confidence scores, etc.
   * - `formatter` receives the current numeric value and returns the display string.
   */
  function animateNumber(el, endValue, options = {}) {
    if (!el) return;
    const { duration = 600, startValue = null, formatter = (v) => Math.round(v).toString() } = options;
    const start = startValue !== null ? startValue : parseFloat(el.textContent) || 0;
    const end = Number(endValue);
    if (isNaN(end) || start === end) {
      el.textContent = formatter(end);
      return;
    }
    const t0 = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - t0) / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      const current = start + (end - start) * eased;
      el.textContent = formatter(current);
      if (t < 1) requestAnimationFrame(frame);
      else el.textContent = formatter(end);
    }
    requestAnimationFrame(frame);
  }

  window.Animations = { staggerIn, fadeOut, pulse, animateNumber };
})();
