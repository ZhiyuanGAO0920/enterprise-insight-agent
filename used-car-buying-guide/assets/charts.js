// assets/charts.js
(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Chart: Radar Comparison ---
  var radarChart = echarts.init(document.getElementById('chart-radar'), null, { renderer: 'svg' });

  radarChart.setOption({
    animation: false,
    tooltip: {
      appendToBody: true,
      trigger: 'item'
    },
    legend: {
      data: ['朗逸', '轩逸', '卡罗拉'],
      bottom: 0,
      textStyle: {
        color: ink,
        fontSize: 13
      },
      itemGap: 30
    },
    radar: {
      indicator: [
        { name: '可靠性', max: 10 },
        { name: '空间表现', max: 10 },
        { name: '用车成本', max: 10 },
        { name: '保值率', max: 10 },
        { name: '驾驶质感', max: 10 },
        { name: '配置丰富度', max: 10 }
      ],
      radius: '65%',
      center: ['50%', '48%'],
      splitNumber: 4,
      axisName: {
        color: ink,
        fontSize: 13,
        fontWeight: 500
      },
      splitLine: {
        lineStyle: {
          color: rule
        }
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: ['rgba(255,255,255,0.3)', 'rgba(245,247,251,0.5)']
        }
      },
      axisLine: {
        lineStyle: {
          color: rule
        }
      }
    },
    series: [{
      type: 'radar',
      emphasis: {
        lineStyle: {
          width: 3
        }
      },
      data: [
        {
          value: [7.5, 9.0, 8.0, 7.0, 9.0, 6.5],
          name: '朗逸',
          lineStyle: {
            color: accent,
            width: 2
          },
          itemStyle: {
            color: accent
          },
          areaStyle: {
            color: accent,
            opacity: 0.15
          }
        },
        {
          value: [6.5, 8.5, 9.0, 7.5, 6.0, 8.0],
          name: '轩逸',
          lineStyle: {
            color: accent2,
            width: 2
          },
          itemStyle: {
            color: accent2
          },
          areaStyle: {
            color: accent2,
            opacity: 0.15
          }
        },
        {
          value: [9.0, 7.5, 8.0, 9.5, 7.0, 7.0],
          name: '卡罗拉',
          lineStyle: {
            color: '#059669',
            width: 2
          },
          itemStyle: {
            color: '#059669'
          },
          areaStyle: {
            color: '#059669',
            opacity: 0.15
          }
        }
      ]
    }]
  });

  window.addEventListener('resize', function() {
    radarChart.resize();
  });

})();
