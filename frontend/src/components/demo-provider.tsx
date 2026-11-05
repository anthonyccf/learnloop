"use client";
import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
} from "react";
import {
  initialPractice,
  migrateDescent,
  practiceReducer,
  restorePractice,
  type ConceptPractice,
  type PracticeAction,
  type PracticeSnapshot,
} from "@/lib/practice-session";

type DemoState = PracticeSnapshot & ConceptPractice & { successes: number };
const Context = createContext<{
  state: DemoState;
  dispatch: React.Dispatch<PracticeAction>;
  storageAvailable: boolean;
} | null>(null);
function parseSaved(value: string | null): unknown {
  try {
    return JSON.parse(value || "null");
  } catch {
    return null;
  }
}
export function DemoProvider({ children }: { children: ReactNode }) {
  const [snapshot, dispatch] = useReducer(
    practiceReducer,
    undefined,
    initialPractice,
  );
  const [storage, updateStorage] = useReducer(
    (_: boolean, next: boolean) => next,
    true,
  );
  useEffect(() => {
    try {
      const saved = restorePractice(
        parseSaved(localStorage.getItem("learnloop-practice-v3")),
      );
      const migrated =
        saved ||
        migrateDescent(
          parseSaved(localStorage.getItem("learnloop-demo-mcq-v2")),
        );
      dispatch({ type: "load", value: migrated || initialPractice() });
    } catch {
      updateStorage(false);
      dispatch({ type: "load", value: initialPractice() });
    }
  }, []);
  useEffect(() => {
    if (snapshot.loaded) {
      try {
        localStorage.setItem("learnloop-practice-v3", JSON.stringify(snapshot));
      } catch {
        updateStorage(false);
      }
    }
  }, [snapshot]);
  const record = snapshot.records[snapshot.conceptId];
  const state = {
    ...snapshot,
    ...record,
    successes: record.independentQuestions.length,
  };
  return (
    <Context.Provider value={{ state, dispatch, storageAvailable: storage }}>
      {children}
    </Context.Provider>
  );
}
export function useDemo() {
  const value = useContext(Context);
  if (!value) throw new Error("DemoProvider missing");
  return value;
}
