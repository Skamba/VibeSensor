import "./styles/app.css";

import { render } from "preact";

import { App, startApp } from "./app";

const root = document.getElementById("app");
if (root === null) {
  throw new Error("VibeSensor UI requires #app");
}
render(<App />, root);
startApp();
