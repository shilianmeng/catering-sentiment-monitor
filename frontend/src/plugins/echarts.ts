/** ECharts 按需注册：只打包用到的图表和组件。 */
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { GraphChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'

use([CanvasRenderer, LineChart, PieChart, GraphChart, GridComponent, LegendComponent, TooltipComponent])
