import "flexlayout-react/style/dark.css";
import "./styles.css";
import { createRoot } from "react-dom/client";
import App from "./App";
import { MarketProvider } from "./store";

createRoot(document.getElementById("root")!).render(
  <MarketProvider>
    <App />
  </MarketProvider>,
);
