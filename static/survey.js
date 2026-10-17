// Questionnaire: show one .survey-step at a time, Typeform style.
// Without this script the form still works as a single long page.

const form = document.querySelector(".survey-form");
const steps = [...form.querySelectorAll(".survey-step")];
const questionCount = steps.length - 1;  // step 0 is the intro
const progress = document.querySelector(".survey-progress");
const progressBar = document.querySelector(".survey-progress-bar");
const count = document.querySelector(".survey-count");
const back = form.querySelector(".survey-back");
const next = form.querySelector(".survey-next");
const submit = form.querySelector(".survey-submit");
const enterHint = form.querySelector(".survey-enter-hint");
const AUTO_ADVANCE_DELAY = 350;

let current = 0;

form.classList.add("is-stepped");
progress.hidden = false;
steps.forEach((step) => step.setAttribute("tabindex", "-1"));

function show(index, direction = "forward") {
    steps[current].classList.remove("is-active", "enter-forward", "enter-back");
    current = Math.max(0, Math.min(index, steps.length - 1));
    const step = steps[current];
    step.classList.add("is-active", `enter-${direction}`);

    const isIntro = current === 0;
    const isLast = current === steps.length - 1;
    back.hidden = isIntro;
    next.hidden = isLast;
    next.textContent = isIntro ? "Start" : "Next";
    submit.hidden = !isLast;
    enterHint.hidden = isLast;

    progressBar.style.width = `${(current / questionCount) * 100}%`;
    progress.setAttribute("aria-hidden", "true");
    count.hidden = isIntro;
    count.textContent = isIntro ? "" : `Question ${current} of ${questionCount}`;

    // Move focus to the question itself (not an input), so phones don't pop up the keyboard
    step.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
}

function goNext() {
    if (current < steps.length - 1) show(current + 1, "forward");
}

function goBack() {
    if (current > 0) show(current - 1, "back");
}

next.addEventListener("click", goNext);
back.addEventListener("click", goBack);

// Enter moves on, except in long answers where it starts a new line
form.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.target.matches("textarea, button, a")) return;
    event.preventDefault();
    if (current === steps.length - 1) form.requestSubmit();
    else goNext();
});

// Questions with one click and nothing to type move on by themselves
form.querySelectorAll("[data-autoadvance] input[type=radio]").forEach((radio) => {
    radio.addEventListener("change", () => {
        const step = radio.closest(".survey-step");
        setTimeout(() => {
            if (steps[current] === step) goNext();
        }, AUTO_ADVANCE_DELAY);
    });
});

// Question 5: once three are ticked, disable the rest
const useful = form.querySelectorAll("#most-useful input[type=checkbox]");
function limitUseful() {
    const full = [...useful].filter((box) => box.checked).length >= 3;
    useful.forEach((box) => { box.disabled = full && !box.checked; });
}
useful.forEach((box) => box.addEventListener("change", limitUseful));
limitUseful();

// Question 1: "None of these" and the product boxes rule each other out
const bought = form.querySelectorAll("input[name=categories_bought]");
bought.forEach((box) => box.addEventListener("change", () => {
    if (!box.checked) return;
    bought.forEach((other) => {
        if (other !== box && (box.value === "none" || other.value === "none")) other.checked = false;
    });
}));

// After a rejected submission, reopen at the question with the problem
show(Number(form.dataset.errorStep) || 0);
