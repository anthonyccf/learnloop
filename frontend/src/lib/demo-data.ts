export type ConceptState =
  "unassessed" | "developing" | "demonstrated" | "review_due";
export type Concept = {
  id: string;
  title: string;
  state: ConceptState;
  x: number;
  y: number;
  prerequisites: string[];
  summary: string;
};
export const labels: Record<ConceptState, string> = {
  unassessed: "Not assessed",
  developing: "Developing",
  demonstrated: "Demonstrated",
  review_due: "Review due",
};
export const concepts: Concept[] = [
  {
    id: "vectors",
    title: "Vectors & matrices",
    state: "demonstrated",
    x: 120,
    y: 70,
    prerequisites: [],
    summary: "Represent inputs and transformations with linear algebra.",
  },
  {
    id: "functions",
    title: "Loss functions",
    state: "demonstrated",
    x: 360,
    y: 70,
    prerequisites: [],
    summary: "Measure the difference between a prediction and its target.",
  },
  {
    id: "derivatives",
    title: "Derivatives",
    state: "demonstrated",
    x: 600,
    y: 70,
    prerequisites: [],
    summary: "Describe how a function changes at a point.",
  },
  {
    id: "gradients",
    title: "Gradients",
    state: "demonstrated",
    x: 240,
    y: 185,
    prerequisites: ["vectors", "derivatives"],
    summary:
      "Combine partial derivatives into a direction of steepest increase.",
  },
  {
    id: "chain",
    title: "Chain rule",
    state: "review_due",
    x: 530,
    y: 185,
    prerequisites: ["derivatives"],
    summary: "Differentiate a composition of functions.",
  },
  {
    id: "descent",
    title: "Gradient descent",
    state: "developing",
    x: 160,
    y: 305,
    prerequisites: ["functions", "gradients"],
    summary: "Use the negative gradient to iteratively reduce the loss.",
  },
  {
    id: "rate",
    title: "Learning rate",
    state: "developing",
    x: 400,
    y: 305,
    prerequisites: ["gradients"],
    summary: "Control the size of each parameter update.",
  },
  {
    id: "backprop",
    title: "Backpropagation",
    state: "review_due",
    x: 640,
    y: 305,
    prerequisites: ["chain", "gradients"],
    summary: "Efficiently propagate loss derivatives through a network.",
  },
  {
    id: "batches",
    title: "Mini-batch learning",
    state: "demonstrated",
    x: 120,
    y: 430,
    prerequisites: ["functions"],
    summary: "Estimate training updates using subsets of the dataset.",
  },
  {
    id: "sgd",
    title: "Stochastic descent",
    state: "developing",
    x: 360,
    y: 430,
    prerequisites: ["descent", "batches"],
    summary: "Use sampled examples to approximate the full gradient.",
  },
  {
    id: "momentum",
    title: "Momentum",
    state: "unassessed",
    x: 600,
    y: 430,
    prerequisites: ["descent"],
    summary: "Accumulate past updates to smooth an optimization trajectory.",
  },
  {
    id: "adam",
    title: "Adam optimizer",
    state: "unassessed",
    x: 480,
    y: 555,
    prerequisites: ["momentum", "sgd"],
    summary: "Combine adaptive step sizes with moving gradient estimates.",
  },
];
export const documents = [
  {
    title: "Training & learning",
    filename: "COMP7608B · Lecture 3",
    pages: 48,
    concepts: 8,
    color: "peach",
  },
  {
    title: "Neural network foundations",
    filename: "COMP7608B · Lecture 2",
    pages: 36,
    concepts: 4,
    color: "lavender",
  },
];
export const questions = [
  {
    prompt: "Why do we subtract the gradient when updating model parameters?",
    hint: "The gradient points toward increasing loss. Which direction would help us go downhill?",
    choices: [
      {
        id: "a",
        text: "To move toward a higher loss and explore more parameters.",
        explanation:
          "Adding the gradient moves uphill locally. Training aims to reduce the loss, not increase it.",
      },
      {
        id: "b",
        text: "To move opposite the direction of increasing loss.",
        explanation:
          "The gradient points toward the steepest local increase. Subtracting it gives a descent direction for a sufficiently small step.",
      },
      {
        id: "c",
        text: "To make every model parameter smaller at each step.",
        explanation:
          "A negative gradient component can make a parameter increase. The goal is to reduce the loss, not to shrink every parameter.",
      },
      {
        id: "d",
        text: "To guarantee that one update reaches the minimum.",
        explanation:
          "Gradient descent usually needs many updates. A single step does not guarantee reaching a minimum.",
      },
    ],
    correctId: "b",
  },
  {
    prompt:
      "The loss keeps oscillating after updates. What is a sensible first adjustment?",
    hint: "Think about a step that carries you past the bottom of a valley. How could you make that step more controlled?",
    choices: [
      {
        id: "a",
        text: "Increase the learning rate so each update travels farther.",
        explanation:
          "If updates are overshooting, larger steps can make the oscillation worse.",
      },
      {
        id: "b",
        text: "Add the gradient instead of subtracting it.",
        explanation:
          "Reversing the update moves toward increasing loss locally rather than addressing the step size.",
      },
      {
        id: "c",
        text: "Reduce the learning rate to take smaller steps.",
        explanation:
          "An overly large learning rate can overshoot a minimum. Smaller steps can make updates more stable, though oscillation can also have other causes.",
      },
      {
        id: "d",
        text: "Set the learning rate to zero and keep training.",
        explanation:
          "A zero learning rate stops parameter updates. The model would no longer learn from those updates.",
      },
    ],
    correctId: "c",
  },
];
