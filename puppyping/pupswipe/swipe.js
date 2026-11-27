(() => {
  const filterForm =
    document.getElementById("auto-filter-form") ||
    document.querySelector("form[data-auto-filter='1']");
  if (!filterForm) {
    return;
  }

  let submitTimer = null;
  let isSubmitting = false;
  const DEFAULT_TEXT_DELAY_MS = 350;
  const DEFAULT_NUMBER_DELAY_MS = 900;
  const CHANGE_DELAY_MS = 140;

  function submitFilters() {
    if (isSubmitting) {
      return;
    }
    isSubmitting = true;
    if (typeof filterForm.requestSubmit === "function") {
      filterForm.requestSubmit();
      return;
    }
    filterForm.submit();
  }

  function scheduleSubmit(delayMs = DEFAULT_TEXT_DELAY_MS) {
    window.clearTimeout(submitTimer);
    submitTimer = window.setTimeout(submitFilters, delayMs);
  }

  function resolveInputDelay(input) {
    const configuredDelay = Number(input?.dataset?.autoSubmitDelayMs || "");
    if (Number.isFinite(configuredDelay) && configuredDelay > 0) {
      return configuredDelay;
    }
    if (input?.type === "number") {
      return DEFAULT_NUMBER_DELAY_MS;
    }
    return DEFAULT_TEXT_DELAY_MS;
  }

  const textInputs = filterForm.querySelectorAll(
    "input[type='text'], input[type='number']"
  );
  const selects = filterForm.querySelectorAll("select");

  textInputs.forEach((input) => {
    input.addEventListener("input", () => {
      scheduleSubmit(resolveInputDelay(input));
    });
    input.addEventListener("change", () => {
      scheduleSubmit(CHANGE_DELAY_MS);
    });
  });

  selects.forEach((select) => {
    select.addEventListener("change", submitFilters);
  });
})();

(() => {
  const menus = document.querySelectorAll("details.account-menu");
  if (!menus.length) {
    return;
  }

  document.addEventListener("click", (ev) => {
    menus.forEach((menu) => {
      if (menu.open && !menu.contains(ev.target)) {
        menu.open = false;
      }
    });
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") {
      return;
    }
    menus.forEach((menu) => {
      if (menu.open) {
        menu.open = false;
      }
    });
  });
})();

(() => {
  const card = document.getElementById("swipe-card");
  const nopeForm = document.getElementById("swipe-nope-form");
  const likeForm = document.getElementById("swipe-like-form");
  const randomForm = document.getElementById("swipe-random-form");
  if (!card || !nopeForm || !likeForm) {
    return;
  }

  const photoContainer = card.querySelector(".card-photo");
  const photoImg = photoContainer?.querySelector("img");
  const metaEl = photoContainer?.querySelector(".carousel-meta");
  const dotEls = Array.from(
    photoContainer?.querySelectorAll(".carousel-dot") || []
  );
  const subscribePhotoInput = document.querySelector(
    "form.subscribe-form input[name='photo']"
  );
  const likeIndicator = card.querySelector(".swipe-indicator.like");
  const nopeIndicator = card.querySelector(".swipe-indicator.nope");

  let photos = [];
  if (photoContainer?.dataset?.photos) {
    try {
      const parsed = JSON.parse(photoContainer.dataset.photos);
      if (Array.isArray(parsed)) {
        photos = parsed.filter(
          (url) =>
            typeof url === "string" && /^(https?:\/\/|\/)/i.test(url.trim())
        );
      }
    } catch {
      photos = [];
    }
  }

  let currentPhotoIndex = Number(photoContainer?.dataset?.photoIndex || 0);
  if (
    !Number.isInteger(currentPhotoIndex) ||
    currentPhotoIndex < 0 ||
    currentPhotoIndex >= photos.length
  ) {
    currentPhotoIndex = 0;
  }

  function preloadAdjacentPhotos() {
    if (photos.length <= 1) {
      return;
    }
    const nextUrl = photos[(currentPhotoIndex + 1) % photos.length];
    const prevUrl =
      photos[(currentPhotoIndex - 1 + photos.length) % photos.length];
    [nextUrl, prevUrl].forEach((url) => {
      if (url) {
        const img = new Image();
        img.referrerPolicy = "no-referrer";
        img.src = url;
      }
    });
  }

  function showPhotoAt(index) {
    if (!photoImg || photos.length <= 1) {
      return;
    }
    currentPhotoIndex = ((index % photos.length) + photos.length) % photos.length;
    photoImg.src = photos[currentPhotoIndex];
    if (photoContainer) {
      photoContainer.dataset.photoIndex = String(currentPhotoIndex);
    }
    if (metaEl) {
      metaEl.textContent = `${currentPhotoIndex + 1} / ${photos.length}`;
    }
    dotEls.forEach((dot, idx) => {
      dot.classList.toggle("is-active", idx === currentPhotoIndex);
    });
    if (subscribePhotoInput) {
      subscribePhotoInput.value = String(currentPhotoIndex);
    }
    preloadAdjacentPhotos();
  }

  function stepPhoto(delta) {
    if (photos.length <= 1) {
      return false;
    }
    showPhotoAt(currentPhotoIndex + delta);
    return true;
  }

  if (photos.length > 1) {
    preloadAdjacentPhotos();
    card.querySelectorAll(".carousel-btn[data-carousel-dir]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        const dir = Number(btn.dataset.carouselDir || 0);
        if (!dir) {
          return;
        }
        ev.preventDefault();
        stepPhoto(dir);
      });
    });
  }

  const previewThreshold = 22;
  const swipeThreshold = Number(card.dataset.swipeThreshold || 110);
  let pointerState = null;
  let horizontalDrag = false;
  let isSubmittingSwipe = false;

  function setIndicatorOpacity(dx) {
    const ratio = Math.min(1, Math.max(0.25, Math.abs(dx) / swipeThreshold));
    if (likeIndicator) {
      likeIndicator.style.opacity = dx > previewThreshold ? String(ratio) : "";
    }
    if (nopeIndicator) {
      nopeIndicator.style.opacity = dx < -previewThreshold ? String(ratio) : "";
    }
  }

  function setPreview(dx) {
    card.classList.toggle("show-like", dx > previewThreshold);
    card.classList.toggle("show-nope", dx < -previewThreshold);
    setIndicatorOpacity(dx);
  }

  function resetVisual() {
    card.style.transform = "translateX(0px) rotate(0deg)";
    card.style.opacity = "1";
    card.style.filter = "none";
    card.style.willChange = "auto";
    card.classList.remove("is-dragging", "show-like", "show-nope");
    if (likeIndicator) {
      likeIndicator.style.opacity = "";
    }
    if (nopeIndicator) {
      nopeIndicator.style.opacity = "";
    }
  }

  function submitSwipe(direction) {
    if (isSubmittingSwipe) {
      return;
    }
    isSubmittingSwipe = true;
    const form = direction === "right" ? likeForm : nopeForm;
    const offscreenX =
      direction === "right" ? window.innerWidth : -window.innerWidth;
    const rotate = direction === "right" ? 14 : -14;

    card.classList.remove("is-dragging");
    card.classList.toggle("show-like", direction === "right");
    card.classList.toggle("show-nope", direction === "left");
    if (likeIndicator && direction === "right") {
      likeIndicator.style.opacity = "1";
    }
    if (nopeIndicator && direction === "left") {
      nopeIndicator.style.opacity = "1";
    }
    card.style.transition =
      "transform 0.18s cubic-bezier(.2,.7,.2,1), opacity 0.18s ease";
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
          ".description, button, a, input, textarea, select, form, summary, details"
        )
    );
  }

  card.addEventListener("pointerdown", (ev) => {
    if (isSubmittingSwipe) {
      return;
    }
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
      captured: false,
    };
    horizontalDrag = false;
    card.classList.add("is-dragging");
    card.style.transition = "none";
    card.style.willChange = "transform, opacity, filter";
  });

  card.addEventListener("pointermove", (ev) => {
    if (!pointerState || ev.pointerId !== pointerState.pointerId) {
      return;
    }
    const dx = ev.clientX - pointerState.startX;
    const dy = ev.clientY - pointerState.startY;

    if (!horizontalDrag) {
      if (Math.abs(dx) < 8) {
        return;
      }
      if (Math.abs(dy) > Math.abs(dx) * 1.15) {
        card.classList.remove("is-dragging");
        return;
      }
      horizontalDrag = true;
      if (
        !pointerState.captured &&
        typeof card.setPointerCapture === "function"
      ) {
        card.setPointerCapture(ev.pointerId);
        pointerState.captured = true;
      }
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
    const wasCaptured = pointerState.captured;
    const wasHorizontalDrag = horizontalDrag;
    const dx = ev.clientX - pointerState.startX;
    const dy = ev.clientY - pointerState.startY;

    if (wasCaptured && typeof card.releasePointerCapture === "function") {
      try {
        card.releasePointerCapture(ev.pointerId);
      } catch {
        // Ignore if pointer capture was already released.
      }
    }

    if (
      wasHorizontalDrag &&
      Math.abs(dx) >= swipeThreshold &&
      Math.abs(dx) > Math.abs(dy) * 1.2
    ) {
      submitSwipe(dx > 0 ? "right" : "left");
      pointerState = null;
      horizontalDrag = false;
      return;
    }

    if (
      !wasHorizontalDrag &&
      Math.abs(dx) < 8 &&
      Math.abs(dy) < 8 &&
      photos.length > 1 &&
      photoContainer &&
      photoContainer.contains(ev.target) &&
      !ev.target.closest("button, a, form")
    ) {
      const rect = photoContainer.getBoundingClientRect();
      if (rect.width > 0) {
        const relX = (ev.clientX - rect.left) / rect.width;
        stepPhoto(relX < 0.35 ? -1 : 1);
      }
    }

    pointerState = null;
    horizontalDrag = false;
    card.style.transition =
      "transform 0.16s ease, opacity 0.16s ease, filter 0.16s ease";
    resetVisual();
  }

  card.addEventListener("pointerup", finishPointer);
  card.addEventListener("pointercancel", finishPointer);

  document.addEventListener("keydown", (ev) => {
    if (isSubmittingSwipe || ev.metaKey || ev.ctrlKey || ev.altKey) {
      return;
    }
    const target = ev.target;
    if (
      target &&
      target.closest(
        "input, textarea, select, [contenteditable='true'], details.account-menu[open]"
      )
    ) {
      return;
    }
    if (ev.key === "ArrowLeft") {
      ev.preventDefault();
      submitSwipe("left");
    } else if (ev.key === "ArrowRight") {
      ev.preventDefault();
      submitSwipe("right");
    } else if ((ev.key === "r" || ev.key === "R") && randomForm) {
      ev.preventDefault();
      isSubmittingSwipe = true;
      randomForm.submit();
    } else if (ev.key === "ArrowUp" || ev.key === "[") {
      if (stepPhoto(-1)) {
        ev.preventDefault();
      }
    } else if (ev.key === "ArrowDown" || ev.key === "]") {
      if (stepPhoto(1)) {
        ev.preventDefault();
      }
    } else if (
      ev.key === " " &&
      (!target || !target.closest("button, a, summary"))
    ) {
      if (stepPhoto(1)) {
        ev.preventDefault();
      }
    }
  });

  resetVisual();
})();

(() => {
  const buttons = document.querySelectorAll(".share-btn");
  if (!buttons.length) {
    return;
  }

  buttons.forEach((btn) => {
    const labelEl = btn.querySelector(".share-label") || btn;
    const defaultLabel = labelEl.textContent || "Copy Share";
    btn.addEventListener("click", async () => {
      const url = (btn.dataset.shareUrl || "").trim();
      const title = (btn.dataset.shareTitle || "Pet profile").trim();
      const shareText = (
        btn.dataset.shareText ||
        `I found a cute pet on PupSwipe. Adoption site: ${url}`
      ).trim();
      if (!url) {
        return;
      }
      try {
        if (navigator.share) {
          await navigator.share({ title, text: shareText, url });
          return;
        }
      } catch {
        // fall through to copy/prompt
      }
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(shareText);
          labelEl.textContent = "Copied";
          window.setTimeout(() => {
            labelEl.textContent = defaultLabel;
          }, 1200);
          return;
        }
      } catch {
        // fall through to prompt
      }
      window.prompt("Copy this share message", shareText);
    });
  });
})();
