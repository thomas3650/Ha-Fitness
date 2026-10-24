// The HA Fitness cards bundle: it registers the cards with Home Assistant's frontend, once that
// has booted (see register.ts).
import { whenFrontendReady } from "./register";
import { registerTodayCard } from "./today-card";
import { registerWorkoutCard } from "./workout-card";
import { registerWorkoutFlow } from "./workout-flow";

whenFrontendReady(() => {
  registerWorkoutFlow();
  registerTodayCard();
  registerWorkoutCard();
});
