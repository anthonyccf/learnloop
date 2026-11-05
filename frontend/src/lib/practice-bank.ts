import { questions as descentQuestions } from "./demo-data";

export type PracticeQuestion = {
  prompt: string;
  hint: string;
  choices: { id: string; text: string; explanation: string }[];
  correctId: string;
};
function mc(
  prompt: string,
  options: [string, string, string, string],
  correct: number,
  explanation: string,
  hint: string,
): PracticeQuestion {
  return {
    prompt,
    hint,
    correctId: "abcd"[correct],
    choices: options.map((text, index) => ({
      id: "abcd"[index],
      text,
      explanation,
    })),
  };
}
// Authored frontend fixtures. These questions are not generated from or verified against the course PDFs.
export const practiceBank: Record<string, PracticeQuestion[]> = {
  vectors: [
    mc(
      "An input is x = [2, 3] and the weights are w = [4, 1]. What is their dot product?",
      ["7", "11", "14", "[8, 3]"],
      1,
      "The dot product adds corresponding products: 2 × 4 + 3 × 1 = 11.",
      "Multiply corresponding entries, then add the results.",
    ),
    mc(
      "A matrix W has shape 3 × 2 and a column vector x has shape 2 × 1. What shape does Wx have?",
      ["2 × 3", "2 × 1", "3 × 1", "3 × 2"],
      2,
      "The inner dimensions match and the outer dimensions remain: (3 × 2)(2 × 1) gives 3 × 1.",
      "Check the inner dimensions, then keep the outer ones.",
    ),
  ],
  functions: [
    mc(
      "The target is 3. Which prediction has the smaller squared error?",
      [
        "Prediction 1",
        "Prediction 2",
        "Both have the same error",
        "The target alone determines the error",
      ],
      1,
      "Prediction 2 has squared error (2 − 3)² = 1; prediction 1 has squared error (1 − 3)² = 4.",
      "Compare the squared distance from each prediction to the target.",
    ),
    mc(
      "Two examples have squared errors 1 and 9. What is their mean squared error?",
      ["10", "4", "9", "5"],
      3,
      "Mean squared error averages the squared errors: (1 + 9) / 2 = 5.",
      "Add the squared errors and divide by the number of examples.",
    ),
  ],
  derivatives: [
    mc(
      "For f(x) = x², what is the derivative at x = 3?",
      ["3", "9", "6", "2"],
      2,
      "The derivative is f′(x) = 2x, so f′(3) = 6. It measures the local rate of change.",
      "Differentiate first, then substitute x = 3.",
    ),
    mc(
      "A differentiable loss has a positive derivative at the current parameter. For a small step, which direction can reduce it?",
      [
        "Decrease the parameter",
        "Increase the parameter",
        "Set the loss to zero",
        "The derivative gives no local information",
      ],
      0,
      "A positive derivative means increasing the parameter locally increases the loss. A small decrease is a descent direction.",
      "A positive slope means the function goes uphill as x increases.",
    ),
  ],
  gradients: [
    mc(
      "A loss has partial derivatives 2 and −3 with respect to two parameters. What is its gradient?",
      ["[−2, 3]", "[2, −3]", "−1", "[2, 3]"],
      1,
      "The gradient is the vector of partial derivatives: [2, −3]. Its negative is a descent direction.",
      "Keep both partial derivatives, including their signs.",
    ),
    mc(
      "The gradient is [2, −3]. Which vector gives the negative-gradient direction?",
      ["[2, −3]", "[3, −2]", "[−2, −3]", "[−2, 3]"],
      3,
      "Negating each component gives [−2, 3]. A gradient-descent update follows that direction with a suitable step size.",
      "Reverse the sign of each component.",
    ),
  ],
  chain: [
    mc(
      "Let u = 3x and y = u². What is dy/dx at x = 2?",
      ["12", "36", "6", "18"],
      1,
      "The chain rule gives dy/dx = (2u)(3). At x = 2, u = 6, so the derivative is 36.",
      "Multiply the outer derivative by the inner derivative.",
    ),
    mc(
      "Why does backpropagation multiply local derivatives along a path?",
      [
        "To average the layer weights",
        "To make all gradients positive",
        "To apply the chain rule through composed functions",
        "To remove the loss function",
      ],
      2,
      "A network composes functions. The chain rule connects the derivative of the loss to earlier parameters through those compositions.",
      "Think of the network as functions nested inside other functions.",
    ),
  ],
  descent: descentQuestions,
  rate: [
    mc(
      "A scalar parameter is 2, its gradient is 3, and the learning rate is 0.1. What is the gradient-descent update?",
      ["2.3", "1.7", "0.6", "−1"],
      1,
      "The new parameter is 2 − 0.1 × 3 = 1.7. The learning rate scales the gradient.",
      "Use current parameter minus learning rate times gradient.",
    ),
    mc(
      "Keeping the gradient fixed, what happens if the learning rate is halved?",
      [
        "The update magnitude doubles",
        "The gradient changes sign",
        "The loss is guaranteed to halve",
        "The update magnitude halves",
      ],
      3,
      "The update is proportional to the learning rate when the gradient is fixed. Halving the learning rate halves the step magnitude.",
      "Focus on the multiplier in the parameter-update rule.",
    ),
  ],
  backprop: [
    mc(
      "What does backpropagation compute during neural-network training?",
      [
        "The derivatives of the loss with respect to parameters",
        "The best learning rate for every model",
        "A new training dataset",
        "Only the final prediction",
      ],
      0,
      "Backpropagation applies the chain rule to compute loss gradients with respect to the network parameters.",
      "Distinguish computing gradients from using them to update weights.",
    ),
    mc(
      "An upstream derivative is 4 and the local derivative on a single path is 0.5. What derivative is propagated along that path?",
      ["4.5", "8", "2", "0.5"],
      2,
      "On this single path, the chain rule multiplies the derivatives: 4 × 0.5 = 2.",
      "Multiply the upstream derivative by the local derivative.",
    ),
  ],
  batches: [
    mc(
      "A dataset has 100 examples and uses batches of 20, without dropping any examples. How many batches make one pass?",
      ["20", "5", "100", "2"],
      1,
      "One pass uses 100 / 20 = 5 batches. Each batch supplies a subset of examples for an update.",
      "Divide the number of examples by the batch size.",
    ),
    mc(
      "Why can gradients from different mini-batches differ at the same parameters?",
      [
        "Each batch must use a different model",
        "The learning rate changes every label",
        "Backpropagation is disabled for small batches",
        "The batches contain different samples",
      ],
      3,
      "Different subsets can produce different estimates of the full-data gradient, even at the same parameters.",
      "The parameter values are fixed; what changed between batches?",
    ),
  ],
  sgd: [
    mc(
      "How does mini-batch stochastic gradient descent usually choose its update direction?",
      [
        "It averages gradients over a sampled mini-batch",
        "It ignores the loss",
        "It updates all weights by the same constant",
        "It always computes the exact full-data gradient",
      ],
      0,
      "A mini-batch gradient estimates the full-data gradient from sampled examples. It is used to update the parameters.",
      "Think about how the chosen subset approximates the full dataset.",
    ),
    mc(
      "Must every mini-batch SGD step reduce the loss on the entire training dataset?",
      [
        "Yes, by definition",
        "Yes, if the batch has two samples",
        "No; a sampled direction can increase the full-data loss on a step",
        "No, because SGD never uses gradients",
      ],
      2,
      "A mini-batch gradient is an estimate. Individual steps need not monotonically reduce the full-data loss.",
      "An estimate from a subset can differ from the full-data gradient.",
    ),
  ],
  momentum: [
    mc(
      "Which information does momentum add to a basic gradient-descent update?",
      [
        "Future test labels",
        "An accumulation of earlier update directions",
        "Only the current loss value",
        "A copy of the input image",
      ],
      1,
      "Momentum maintains a running accumulation of past gradient directions and uses it in the update.",
      "The name suggests carrying part of earlier movement forward.",
    ),
    mc(
      "Why can momentum help when gradients repeatedly point in a consistent direction?",
      [
        "It guarantees the global optimum",
        "It removes the need for a learning rate",
        "It forces every parameter to decrease",
        "Past contributions reinforce movement in that direction",
      ],
      3,
      "Consistent directions can reinforce the accumulated update, while rapidly alternating components can partially cancel.",
      "Consider adding several arrows that point in the same direction.",
    ),
  ],
  adam: [
    mc(
      "Adam maintains moving estimates of which gradient quantities?",
      [
        "Gradients and squared gradients",
        "Training labels and predictions only",
        "Only the largest gradient ever seen",
        "The exact Hessian and its inverse",
      ],
      0,
      "Adam tracks first- and second-moment estimates using gradients and squared gradients, then uses them in its parameter updates.",
      "One estimate tracks direction; the other tracks gradient scale.",
    ),
    mc(
      "Why can Adam use different effective step sizes for different parameters?",
      [
        "It gives every parameter a separate training dataset",
        "It never uses a learning rate",
        "It scales updates using per-parameter gradient statistics",
        "It sets all gradients to one",
      ],
      2,
      "Adam uses per-parameter moment estimates to scale updates. The effective scaling can therefore differ between parameters.",
      "Its stored gradient statistics are maintained separately for each parameter.",
    ),
  ],
};
