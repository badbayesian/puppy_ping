(() => {
  const card = document.getElementById("swipe-card");
  const nopeForm = document.getElementById("swipe-nope-form");
  const likeForm = document.getElementById("swipe-like-form");
  if (!card || !nopeForm || !likeForm) {
    return;
  }

  const previewThreshold = 22;
  const swipeThreshold = Number(card.dataset.swipeThreshold || 110);
  let pointerState = null;
  let horizontalDrag = false;

  function setPreview(dx) {
    card.classList.toggle("show-like", dx > previewThreshold);
    card.classList.toggle("show-nope", dx < -previewThreshold);
  }

  function resetVisual() {
    card.style.transform = "translateX(0px) rotate(0deg)";
    card.style.opacity = "1";
    card.style.filter = "none";
    card.style.willChange = "auto";
    card.classList.remove("is-dragging", "show-like", "show-nope");
  }

  function submitSwipe(direction) {
    const form = direction === "right" ? likeForm : nopeForm;
    const offscreenX = direction === "right" ? window.innerWidth : -window.innerWidth;
    const rotate = direction === "right" ? 14 : -14;

    card.classList.remove("is-dragging");
    card.classList.toggle("show-like", direction === "right");
    card.classList.toggle("show-nope", direction === "left");
    card.style.transition = "transform 0.18s cubic-bezier(.2,.7,.2,1), opacity 0.18s ease";
    card.style.transform = `translateX(${offscreenX}px) translateY(-10px) rotate(${rotate}deg)`;
    card.style.opacity = "0.22";
    card.style.filter = "saturate(1.15)";

    window.setTimeout(() => {
      form.submit();
    }, 100);
  }

  function shouldIgnoreTarget(target) {
    return Boolean(
      target &&
        target.closest(
          ".card-body, button, a, input, textarea, select, form"
        )
    );
  }

  card.addEventListener("pointerdown", (ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) {
      return;
    }
    if (shouldIgnoreTarget(ev.target)) {
      return;
    }
    pointerState = {
      pointerId: ev.pointerId,
      startX: ev.clientX,
      startY: ev.clientY,
    };
    horizontalDrag = false;
    card.classList.add("is-dragging");
    card.style.transition = "none";
    card.style.willChange = "transform, opacity, filter";
    if (typeof card.setPointerCapture === "function") {
      card.setPointerCapture(ev.pointerId);
    }
  });

  card.addEventListener("pointermove", (ev) => {
    if (!pointerState || ev.pointerId !== pointerState.pointerId) {
      return;
    }
    const dx = ev.clientX - pointerState.startX;
    const dy = ev.clientY - pointerState.startY;

    if (!horizontalDrag) {
      if (Math.abs(dx) < 6) {
        return;
      }
      if (Math.abs(dy) > Math.abs(dx) * 1.2) {
        card.classList.remove("is-dragging");
        return;
      }
      horizontalDrag = true;
    }

    const rotate = Math.max(-16, Math.min(16, dx * 0.05));
    const lift = Math.min(14, Math.abs(dx) * 0.06);
    const saturation = 1 + Math.min(0.22, Math.abs(dx) / 520);
    card.style.transform = `translateX(${dx}px) translateY(${-lift}px) rotate(${rotate}deg)`;
    card.style.opacity = "1";
    card.style.filter = `saturate(${saturation})`;
    setPreview(dx);
  });

  function finishPointer(ev) {
    if (!pointerState || ev.pointerId !== pointerState.pointerId) {
      return;
    }
    const dx = ev.clientX - pointerState.startX;
    const dy = ev.clientY - pointerState.startY;
    pointerState = null;
    horizontalDrag = false;

    if (typeof card.releasePointerCapture === "function") {
      try {
        card.releasePointerCapture(ev.pointerId);
      } catch {
        // Ignore if pointer capture was already released.
      }
    }

    if (horizontalDrag && Math.abs(dx) >= swipeThreshold && Math.abs(dx) > Math.abs(dy) * 1.2) {
      submitSwipe(dx > 0 ? "right" : "left");
      return;
    }

    card.style.transition = "transform 0.16s ease, opacity 0.16s ease, filter 0.16s ease";
    resetVisual();
  }

  card.addEventListener("pointerup", finishPointer);
  card.addEventListener("pointercancel", finishPointer);

  resetVisual();
})();
