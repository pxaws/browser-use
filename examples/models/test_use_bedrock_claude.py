"""
Automated news analysis and sentiment scoring using Bedrock.

@dev Ensure AWS environment variables are set correctly for Bedrock access.
"""

import argparse
import asyncio
import os
import logging
import sys
from typing import Optional

# disable browser-use's built-in LLM API-key check
os.environ["SKIP_LLM_API_KEY_VERIFICATION"] = "True"

# now it's safe to import
from browser_use import Agent, Browser, BrowserConfig, BrowserContextConfig
from browser_use.browser.context import BrowserContext

import asyncio
import warnings
from browser_use.controller.service import Controller
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ClickDataPointAction(BaseModel):
    index: Optional[int] = None
    xpath: Optional[str] = None
    selector: Optional[str] = None


controller = Controller()



@controller.registry.action(
    "Click a fault data point",
    param_model=ClickDataPointAction,
)
async def ClickDataPointInMetric(params: ClickDataPointAction, browser: BrowserContext):
    page = await browser.get_current_page()
    logger.info("Executing ClickDataPointInMetric for selector: ========")

    # 1. Grab the iframe and its Frame object
    iframe_el = await page.query_selector("iframe#microConsole-Pulse")
    assert iframe_el, "CloudWatch iframe not found"
    frame = await iframe_el.content_frame()
    assert frame, "Cannot access iframe content"

    # 2. Locate the Faults SVG inside that frame
    svg = frame.locator('.cwdb-chart svg[aria-label="Faults and Errors graph"]')
    handle = await svg.element_handle()
    assert handle, "Faults SVG not found"

    # 3. In-frame evaluate: parse the <path>, pick its highest point, map → screen coords
    point = await frame.evaluate(
        """(svg) => {
            // print out the position of the mouse click
            document.addEventListener('click', function(e) {
                console.log(`Mouse clicked at: screen(${e.screenX}, ${e.screenY}), client(${e.clientX}, ${e.clientY})`);
            });
            
            const path = svg.querySelector('.metrics .left .metric.line.dimmable path');
            if (!path) throw 'Faults path not found';
            const coords = path.getAttribute('d')
              .slice(1)
              .split('L')
              .map(s => s.split(',').map(Number));
            const [xData, yData] = coords.reduce(
              (best, curr) => curr[1] < best[1] ? curr : best,
              coords[0]
            );
            const pt = svg.createSVGPoint();
            pt.x = xData; pt.y = yData;
            const screenPt = pt.matrixTransform(svg.getScreenCTM());
            return { x: screenPt.x, y: screenPt.y };
            }""",
        handle,
    )

    # 4. Compute hover/click position relative to the SVG box
    box = await svg.bounding_box()
    assert box, "Cannot get SVG bounding box"
    rel_x = point["x"] - box["x"]
    rel_y = point["y"] - box["y"]

    # 5. Hover to show tooltip, pause, then click
    await svg.hover(position={"x": rel_x, "y": rel_y})
    await page.wait_for_timeout(150)  # allow hover‐tooltip to render
    await svg.click(position={"x": rel_x, "y": rel_y})


# ─── your custom controller ───────────────────────────────────────────────────
# class ChartController(BaseController):
#     async def click_highest_point_for_series(
#         self, container_selector: str, series_index: int = 0, sample_count: int = 200
#     ):
#         """
#         Within `container_selector`, finds the Nth <path> (series_index),
#         samples along it, picks the visually highest point (min y), and clicks.
#         """
#         # wait for the chart container + its <svg>
#         await self.page.wait_for_selector(container_selector)
#         coords = await self.page.evaluate(
#             """(sel, idx, samples) => {
#                  const container = document.querySelector(sel);
#                  const svg = container?.querySelector('svg');
#                  if (!svg) throw 'SVG not found';
#                  const paths = Array.from(svg.querySelectorAll('path'));
#                  const path = paths[idx];
#                  const total = path.getTotalLength();
#                  let best = null;
#                  for (let i = 0; i <= samples; i++) {
#                    const pt = path.getPointAtLength((i/samples)*total);
#                    if (!best || pt.y < best.y) best = pt;
#                  }
#                  const r = svg.getBoundingClientRect();
#                  return { x: best.x + r.left + window.scrollX,
#                           y: best.y + r.top  + window.scrollY };
#              }""",
#             container_selector,
#             series_index,
#             sample_count,
#         )
#         await self.page.mouse.move(coords.x, coords.y)
#         await self.page.mouse.click(coords.x, coords.y)


import boto3
from botocore.config import Config
from langchain_aws import ChatBedrockConverse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# from browser_use import Agent
# from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.controller.service import Controller


def get_llm():
    config = Config(retries={"max_attempts": 10, "mode": "adaptive"})
    bedrock_client = boto3.client(
        "bedrock-runtime", region_name="us-east-1", config=config
    )

    return ChatBedrockConverse(
        model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        temperature=0.0,
        max_tokens=None,
        client=bedrock_client,
    )

    # 9. Locate the “Faults and Errors” chart.
    # 10. Within that chart, identify the blue “Faults” series and click the single data point at its highest peak.
    # Important:
    # - Wait for each element to load before interacting


task = """Navigate to AWS Console and check results.

        Here are the specific steps:

        1. Go to https://tiny.amazon.com/zjggl7m6/IsenLink and wait a few seconds for the page to fully loaded
        2. Scroll down one page. Find out the search field with the placeholder text "Filter services and resources by text, property or value". 
        3. In the search field, type 'visits-service-java' and press Enter to do the filtering. Wait 1 second
        4. Click the hyperlink "visits-service-java" in the "Services" list in the main panel. Wait 1 second 
        5. Wait for "Service operations" button next to "Overview" is clickable
        6. Click the "Service operations" button inside the page
        7. In the search field under "Service operations" type 'POST /owners/*/pets/{petId}/visits' and press Enter to do the filtering
        8. Click a fault data point
        """

task2 = """Navigate to AWS Console and check results.

        Here are the specific steps:

        1. In the right panel, click the first link under "Trace ID"
        2. In the new page, wait for the right panel to pop up
        3. In the right panel, click the button "Exception" next to the button "Metadata"
        4. Check the message looks like "The level of configured provisioned throughput for the table was exceeded."

        """

parser = argparse.ArgumentParser()
parser.add_argument(
    "--query", type=str, help="The query for the agent to execute", default=task
)
args = parser.parse_args()

parser2 = argparse.ArgumentParser()
parser2.add_argument(
    "--query", type=str, help="The query for the agent to execute", default=task2
)
args2 = parser2.parse_args()

llm = get_llm()


async def main():
    browser = Browser(
        config=BrowserConfig(
            browser_binary_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            new_context_config=BrowserContextConfig(
                # don’t waste 0.5s per page—go down to 0.1s
                minimum_wait_page_load_time=0.1,
                # only wait for 0.2s of network idle instead of 1.0s
                wait_for_network_idle_page_load_time=0.2,
                # bail out after 2s if it hangs
                maximum_wait_page_load_time=2.0,
                # turn off drawing highlights around every element
                highlight_elements=False,
                # only include the viewport (instead of ±500px) when LLM snapshots page
                # viewport_expansion=0,
            ),
        )
    )

    # controller = ChartController()
    async with await browser.new_context() as context:
        # teach the model how to invoke your helper:
        extend_system_message = "When I say 'Click a fault data point', run the function ClickDataPointInMetric."

        # instantiate *inside* the running loop
        agent = Agent(
            task=args.query,
            llm=llm,
            controller=controller,
            browser_context=context,
            validate_output=True,
            enable_memory=False,
            extend_system_message=extend_system_message,
        )

        # await agent.run(max_steps=30)
        await agent.run()
        input("Click a dip in availability graph and then press Enter to continue ...")

        next_agent = Agent(
            task=args2.query,
            llm=llm,
            controller=Controller(),
            browser_context=context,
            validate_output=True,
            enable_memory=False,
        )
        await next_agent.run()

        input("Press Enter to close the browser...")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
