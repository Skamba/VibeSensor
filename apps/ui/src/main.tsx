import "./styles/app.css";

import { render } from "preact";

import { App } from "./app";
import { startFeatures } from "./app/feature_wiring";

const root = document.getElementById("app");
if (root === null) {
  throw new Error("VibeSensor UI requires #app");
}
render(<App />, root);
startFeatures();
