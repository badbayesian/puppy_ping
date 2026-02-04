const stack = document.getElementById("stack");
const stateEl = document.getElementById("state");
const statsEl = document.getElementById("stats");
const profileLink = document.getElementById("profile-link");
const buttons = document.querySelectorAll(".btn");

const SWIPE_THRESHOLD = 120;
const ROTATION_DIVISOR = 18;

let puppies = [];
let index = 0;
let activeCard = null;
let startX = 0;
let startY = 0;
let currentX = 0;
let currentY = 0;
let isDragging = false;

function setState(message) {
  stateEl.textContent = message;
  stateEl.style.display = "grid";
}

function clearState() {
  stateEl.style.display = "none";
}

function formatAge(puppy) {
  if (puppy.age_raw) return puppy.age_raw;
  if (puppy.age_months !== null && puppy.age_months !== undefined) {
    return `${puppy.age_months} months`;
  }
  return "Age unknown";
}

function formatWeight(puppy) {
  if (puppy.weight_lbs !== null && puppy.weight_lbs !== undefined) {
    return `${puppy.weight_lbs} lbs`;
  }
  return null;
}

function getPrimaryImage(puppy) {
  if (puppy.primary_image) return puppy.primary_image;
  const media = puppy.media || {};
  if (Array.isArray(media.images) && media.images.length) return media.images[0];
  return null;
}

function buildBadges(puppy) {
  const badges = [];
  if (puppy.location) badges.push({ label: puppy.location, alt: true });
  if (puppy.gender) badges.push({ label: puppy.gender, alt: false });
  const weight = formatWeight(puppy);
  if (weight) badges.push({ label: weight, alt: false });
  if (puppy.status) badges.push({ label: puppy.status, alt: true });

  const ratings = puppy.ratings || {};
  const ratingLabels = {
    children: "Good with kids",
    dogs: "Dog friendly",
    cats: "Cat friendly",
    home_alone: "Home alone",
    activity: "Activity",
    environment: "Environment",
  };

  Object.keys(ratingLabels).forEach((key) => {
    const value = ratings[key];
    if (value !== null && value !== undefined) {
      badges.push({ label: `${ratingLabels[key]}: ${value}/5`, alt: false });
    }
  });

  return badges.slice(0, 6);
}

function createCard(puppy) {
  const card = document.createElement("article");
  card.className = "card enter";

  const photo = document.createElement("div");
  photo.className = "card-photo";

  const likeStamp = document.createElement("div");
  likeStamp.className = "stamp like";
  likeStamp.textContent = "LIKE";
  const nopeStamp = document.createElement("div");
  nopeStamp.className = "stamp nope";
  nopeStamp.textContent = "NOPE";

  const imageUrl = getPrimaryImage(puppy);
  if (imageUrl) {
    const img = document.createElement("img");
    img.src = imageUrl;
    img.alt = puppy.name ? `Photo of ${puppy.name}` : "Puppy photo";
    photo.appendChild(img);
  } else {
    const fallback = document.createElement("div");
    fallback.className = "photo-fallback";
    fallback.textContent = puppy.name ? puppy.name.charAt(0) : "P";
    photo.appendChild(fallback);
  }

  photo.appendChild(likeStamp);
  photo.appendChild(nopeStamp);

  const body = document.createElement("div");
  body.className = "card-body";

  const title = document.createElement("div");
  title.className = "card-title";
  const h2 = document.createElement("h2");
  h2.textContent = puppy.name || "Unnamed";
  const age = document.createElement("span");
  age.textContent = formatAge(puppy);
  title.appendChild(h2);
  title.appendChild(age);

  const subtitle = document.createElement("div");
  subtitle.className = "card-subtitle";
  const bits = [puppy.breed, puppy.location].filter(Boolean);
  subtitle.textContent = bits.length ? bits.join(" • ") : "Adoptable pup";

  const badges = document.createElement("div");
  badges.className = "badges";
  buildBadges(puppy).forEach((badge) => {
    const span = document.createElement("span");
    span.className = `badge${badge.alt ? " alt" : ""}`;
    span.textContent = badge.label;
    badges.appendChild(span);
  });

  const description = document.createElement("p");
  description.className = "description";
  description.textContent = puppy.description || "No description yet.";

  body.appendChild(title);
  body.appendChild(subtitle);
  body.appendChild(badges);
  body.appendChild(description);

  card.appendChild(photo);
  card.appendChild(body);

  return card;
}

function updateStats() {
  if (!puppies.length) {
    statsEl.textContent = "0 pups";
    return;
  }
  const position = Math.min(index + 1, puppies.length);
  statsEl.textContent = `${position} of ${puppies.length} pups`;
}

function updateProfileLink() {
  const current = puppies[index];
  if (current && current.url) {
    profileLink.href = current.url;
    profileLink.style.visibility = "visible";
  } else {
    profileLink.href = "#";
    profileLink.style.visibility = "hidden";
  }
}

function renderStack() {
  stack.querySelectorAll(".card").forEach((card) => card.remove());

  if (!puppies.length) {
    setState("No puppies found. Run the scraper to fill the database.");
    updateStats();
    updateProfileLink();
    return;
  }

  if (index >= puppies.length) {
    setState("That is everyone. Refresh to pull new pups.");
    updateStats();
    updateProfileLink();
    return;
  }

  clearState();

  const visible = puppies.slice(index, index + 3);
  visible.forEach((puppy, i) => {
    const card = createCard(puppy);
    card.style.zIndex = `${100 - i}`;
    card.style.transform = `translateY(${i * 12}px) scale(${1 - i * 0.04})`;
    card.style.opacity = `${1 - i * 0.08}`;

    if (i === 0) {
      attachDrag(card);
      activeCard = card;
    }

    stack.appendChild(card);
  });

  updateStats();
  updateProfileLink();
}

function attachDrag(card) {
  card.addEventListener("pointerdown", (event) => {
    if (isDragging) return;
    isDragging = true;
    card.classList.add("is-dragging");
    card.setPointerCapture(event.pointerId);
    startX = event.clientX;
    startY = event.clientY;
  });

  card.addEventListener("pointermove", (event) => {
    if (!isDragging) return;
    currentX = event.clientX - startX;
    currentY = event.clientY - startY;
    const rotation = currentX / ROTATION_DIVISOR;
    card.style.transform = `translate(${currentX}px, ${currentY}px) rotate(${rotation}deg)`;

    if (currentX > 40) {
      card.classList.add("show-like");
      card.classList.remove("show-nope");
    } else if (currentX < -40) {
      card.classList.add("show-nope");
      card.classList.remove("show-like");
    } else {
      card.classList.remove("show-like", "show-nope");
    }
  });

  card.addEventListener("pointerup", () => {
    if (!isDragging) return;
    isDragging = false;
    card.classList.remove("is-dragging");

    const direction =
      currentX > SWIPE_THRESHOLD
        ? "right"
        : currentX < -SWIPE_THRESHOLD
        ? "left"
        : null;

    if (!direction) {
      card.style.transform = "translateY(0) scale(1)";
      card.classList.remove("show-like", "show-nope");
      currentX = 0;
      currentY = 0;
      return;
    }

    commitSwipe(direction, card);
  });
}

function commitSwipe(direction, card) {
  if (!card) return;
  const puppy = puppies[index];
  sendSwipe(puppy, direction);

  const flyX = direction === "right" ? window.innerWidth * 1.2 : -window.innerWidth * 1.2;
  const flyY = currentY || -40;
  const rotation = direction === "right" ? 24 : -24;

  card.style.transform = `translate(${flyX}px, ${flyY}px) rotate(${rotation}deg)`;
  card.style.opacity = "0";

  index += 1;
  currentX = 0;
  currentY = 0;

  card.addEventListener(
    "transitionend",
    () => {
      renderStack();
    },
    { once: true }
  );
}

function sendSwipe(puppy, direction) {
  if (!puppy || !puppy.dog_id) return;
  fetch("/api/swipes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dog_id: puppy.dog_id, swipe: direction }),
  }).catch(() => {});
}

function forceSwipe(direction) {
  const card = stack.querySelector(".card");
  if (!card) return;
  card.classList.add(direction === "right" ? "show-like" : "show-nope");
  commitSwipe(direction, card);
}

function bindControls() {
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "like") {
        forceSwipe("right");
      }
      if (action === "nope") {
        forceSwipe("left");
      }
      if (action === "refresh") {
        loadPuppies();
      }
    });
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      forceSwipe("left");
    }
    if (event.key === "ArrowRight") {
      forceSwipe("right");
    }
    if (event.key === "r") {
      loadPuppies();
    }
  });
}

async function loadPuppies() {
  setState("Loading puppies from the database...");
  statsEl.textContent = "Loading pups...";
  try {
    const response = await fetch("/api/puppies?limit=60");
    if (!response.ok) throw new Error("failed to load");
    const data = await response.json();
    puppies = Array.isArray(data.items) ? data.items : [];
    index = 0;
    renderStack();
  } catch (err) {
    setState("Unable to load puppies. Check the server and database.");
    statsEl.textContent = "Offline";
  }
}

bindControls();
loadPuppies();
