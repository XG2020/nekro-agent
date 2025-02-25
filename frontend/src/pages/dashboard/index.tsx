import React, { useState, useEffect, useCallback } from 'react'
import { Box, Tabs, Tab, Grid, Stack } from '@mui/material'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import {
  Message as MessageIcon,
  Group as GroupIcon,
  Code as CodeIcon,
  CheckCircle as CheckCircleIcon,
} from '@mui/icons-material'
import { dashboardApi, RealTimeDataPoint } from '../../services/api/dashboard'
import { StatCard } from './components/StatCard'
import { TrendsChart } from './components/TrendsChart'
import { DistributionsCard } from './components/DistributionsCard'
import { RankingList } from './components/RankingList'
import { RealTimeStats } from './components/RealTimeStats'
import { createEventStream } from '../../services/api/utils/stream'

// 定义时间范围类型
type TimeRange = 'day' | 'week' | 'month'

const DashboardContent: React.FC = () => {
  // 状态
  const [timeRange, setTimeRange] = useState<TimeRange>('day')
  const [realTimeData, setRealTimeData] = useState<RealTimeDataPoint[]>([])
  const [granularity, setGranularity] = useState<number>(10) // 默认10分钟粒度
  const [streamCancel, setStreamCancel] = useState<(() => void) | null>(null)

  // 处理实时数据
  const handleRealTimeData = useCallback((data: string) => {
    try {
      const newData = JSON.parse(data) as RealTimeDataPoint
      setRealTimeData(prev => {
        // 检查是否已存在相同时间戳的数据点
        const existingIndex = prev.findIndex(item => item.timestamp === newData.timestamp)

        if (existingIndex >= 0) {
          // 更新已存在的数据点
          const updated = [...prev]
          updated[existingIndex] = newData
          return updated
        } else {
          // 添加新数据点并保持按时间排序
          const updated = [...prev, newData].sort(
            (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          )

          // 限制数据点数量，保留最近50个数据点
          if (updated.length > 50) {
            return updated.slice(updated.length - 50)
          }
          return updated
        }
      })
    } catch (error) {
      console.error('解析实时数据失败:', error)
    }
  }, [])

  // 初始化实时数据流
  useEffect(() => {
    // 取消之前的流
    if (streamCancel) {
      streamCancel()
    }

    // 清空之前的数据
    setRealTimeData([])

    // 创建新的流连接
    const cancelStream = createEventStream({
      endpoint: `/dashboard/stats/stream?granularity=${granularity}`,
      onMessage: handleRealTimeData,
      onError: error => console.error('仪表盘数据流错误:', error),
    })

    // 保存取消函数
    setStreamCancel(() => cancelStream)

    return () => {
      if (cancelStream) cancelStream()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handleRealTimeData, granularity])

  // 处理粒度变更
  const handleGranularityChange = useCallback((newGranularity: number) => {
    setGranularity(newGranularity)
  }, [])

  // 查询概览数据
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['dashboard-overview', timeRange],
    queryFn: () => dashboardApi.getOverview({ time_range: timeRange }),
  })

  // 查询趋势数据
  const { data: trends, isLoading: trendsLoading } = useQuery({
    queryKey: ['dashboard-trends', timeRange],
    queryFn: () =>
      dashboardApi.getTrends({
        metrics: 'messages,sandbox_calls,success_calls,failed_calls,success_rate',
        time_range: timeRange,
        interval: timeRange === 'day' ? 'hour' : 'day',
      }),
  })

  // 查询分布数据
  const { data: distributions, isLoading: distributionsLoading } = useQuery({
    queryKey: ['dashboard-distributions', timeRange],
    queryFn: () => dashboardApi.getDistributions({ time_range: timeRange }),
  })

  // 查询活跃用户排名
  const { data: activeUsers, isLoading: usersLoading } = useQuery({
    queryKey: ['dashboard-active-ranking', 'users', timeRange],
    queryFn: () =>
      dashboardApi.getActiveRanking({
        ranking_type: 'users',
        time_range: timeRange,
      }),
  })

  const handleTimeRangeChange = (_: React.SyntheticEvent, newValue: TimeRange) => {
    setTimeRange(newValue)
  }

  return (
    <Box className="h-[calc(100vh-90px)] flex flex-col gap-3 overflow-auto p-2">
      {/* 时间范围选择器 */}
      <Tabs value={timeRange} onChange={handleTimeRangeChange} className="mb-2">
        <Tab value="day" label="今天" />
        <Tab value="week" label="本周" />
        <Tab value="month" label="本月" />
      </Tabs>

      {/* 统计卡片 */}
      <Stack direction="row" spacing={2} className="flex-shrink-0">
        <StatCard
          title="总消息数"
          value={overview?.total_messages || 0}
          loading={overviewLoading}
          icon={<MessageIcon />}
        />
        <StatCard
          title="活跃会话"
          value={overview?.active_sessions || 0}
          loading={overviewLoading}
          icon={<GroupIcon />}
        />
        <StatCard
          title="独立用户"
          value={overview?.unique_users || 0}
          loading={overviewLoading}
          icon={<MessageIcon />}
        />
        <StatCard
          title="沙盒执行"
          value={overview?.total_sandbox_calls || 0}
          loading={overviewLoading}
          icon={<CodeIcon />}
        />
        <StatCard
          title="执行成功率"
          value={`${overview?.success_rate || 0}%`}
          loading={overviewLoading}
          icon={<CheckCircleIcon />}
          color={(overview?.success_rate || 0) >= 90 ? 'success.main' : 'warning.main'}
        />
      </Stack>

      {/* 趋势图和实时数据 */}
      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <RealTimeStats
            title="实时数据"
            data={realTimeData}
            granularity={granularity}
            onGranularityChange={handleGranularityChange}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <TrendsChart
            title="概览"
            data={trends}
            loading={trendsLoading}
            metrics={['messages', 'sandbox_calls']}
            timeRange={timeRange}
          />
        </Grid>
      </Grid>

      {/* 消息和执行趋势 */}
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <TrendsChart
            title="执行状态"
            data={trends}
            loading={trendsLoading}
            metrics={['success_calls', 'failed_calls']}
            timeRange={timeRange}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <TrendsChart
            title="响应成功率"
            data={trends}
            loading={trendsLoading}
            metrics={['success_rate']}
            timeRange={timeRange}
          />
        </Grid>
      </Grid>

      {/* 分布统计与排名 */}
      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <DistributionsCard
            stopTypeData={distributions?.stop_type}
            messageTypeData={distributions?.message_type}
            loading={distributionsLoading}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <RankingList title="活跃排名" data={activeUsers} loading={usersLoading} type="users" />
        </Grid>
      </Grid>
    </Box>
  )
}

// 提供查询客户端
const DashboardPage: React.FC = () => {
  const queryClient = new QueryClient()

  return (
    <QueryClientProvider client={queryClient}>
      <DashboardContent />
    </QueryClientProvider>
  )
}

export default DashboardPage
