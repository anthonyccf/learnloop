"""Real models: goals, action planning, source-backed rubrics and optional reasoning.

Uses a disposable schema/vector owner. Answers deliberately use the private
reference answer as a test oracle; this validates workflow, not learning gains.
"""

from scripts.validation.difficulty_levels import main

if __name__ == "__main__":
    main("planning-assessment-validation", exercise_plans=True)
