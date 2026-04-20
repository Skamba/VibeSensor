import { describe, expect, test } from "vitest";
import { createSpectrumPanel } from "../src/app/views/spectrum_panel";

describe("createSpectrumPanel", () => {
  test("keeps hover-only inspector updates out of the live announcer", () => {
    const panel = createSpectrumPanel();

    panel.view.renderInspector({
      text: "Hover:Front Right Wheel:10.0:12.0:No reference band",
      announce: false,
    });

    expect(panel.props.inspectorText.value).toBe("Hover:Front Right Wheel:10.0:12.0:No reference band");
    expect(panel.props.inspectorAnnouncement.value).toBe("");

    panel.view.renderInspector({
      text: "Selected:Front Right Wheel:10.0:12.0:No reference band",
      announce: true,
    });

    expect(panel.props.inspectorText.value).toBe("Selected:Front Right Wheel:10.0:12.0:No reference band");
    expect(panel.props.inspectorAnnouncement.value).toBe("Selected:Front Right Wheel:10.0:12.0:No reference band");
  });
});
