import React, { useEffect, useState } from 'react'
import { Tabs, Col, Row, Button, Spin } from 'antd'
import { Loading } from 'lib/utils'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { DashboardItemType } from '~/types'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import './InsightHistoryPanel.scss'
import dayjs from 'dayjs'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { router } from 'kea-router'
import { ViewType } from '../insightLogic'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
    TEAM: 'TEAM',
}

const { TabPane } = Tabs

interface InsightHistoryPanelProps {
    onChange: () => void
}

function InsightPane({
    data,
    loading,
    loadMore,
    loadingMore,
    footer,
}: {
    data: DashboardItemType[]
    loading: boolean
    loadMore?: () => void
    loadingMore: boolean
    footer: (item: DashboardItemType) => JSX.Element
}): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights, updateInsight } = useActions(insightHistoryLogic)
    const { duplicateDashboardItem } = useActions(dashboardItemsModel)

    useEffect(() => {
        loadInsights()
        loadSavedInsights()
        loadTeamInsights()
    }, [])

    return (
        <Row gutter={[16, 16]}>
            {loading && <Loading />}
            {data &&
                data.map((insight: DashboardItemType, index: number) => (
                    <Col xs={8} key={insight.id} style={{ height: 270 }}>
                        <DashboardItem
                            item={{ ...insight, color: null }}
                            key={insight.id + '_user'}
                            loadDashboardItems={() => {
                                loadInsights()
                                loadSavedInsights()
                                loadTeamInsights()
                            }}
                            saveDashboardItem={updateInsight}
                            onClick={() => {
                                const _type: DisplayedType =
                                    insight.filters.insight === ViewType.RETENTION
                                        ? 'RetentionContainer'
                                        : insight.filters.display
                                router.actions.push(displayMap[_type].link(insight))
                            }}
                            moveDashboardItem={
                                insight.saved
                                    ? (item: DashboardItemType, dashboardId: number) => {
                                          duplicateDashboardItem(item, dashboardId)
                                      }
                                    : undefined
                            }
                            preventLoading={true}
                            footer={<div className="dashboard-item-footer">{footer(insight)}</div>}
                            index={index}
                            isOnEditMode={false}
                        />
                    </Col>
                ))}
            {loadMore && (
                <div
                    style={{
                        textAlign: 'center',
                        margin: '12px auto',
                        height: 32,
                        lineHeight: '32px',
                    }}
                >
                    {loadingMore ? <Spin /> : <Button onClick={loadMore}>Load more</Button>}
                </div>
            )}
        </Row>
    )
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = () => {
    const {
        insights,
        insightsLoading,
        loadingMoreInsights,
        insightsNext,
        savedInsights,
        savedInsightsLoading,
        loadingMoreSavedInsights,
        savedInsightsNext,
        teamInsights,
        teamInsightsLoading,
        loadingMoreTeamInsights,
        teamInsightsNext,
    } = useValues(insightHistoryLogic)
    const { loadNextInsights, loadNextSavedInsights, loadNextTeamInsights } = useActions(insightHistoryLogic)

    const [activeTab, setActiveTab] = useState(InsightHistoryType.RECENT)

    return (
        <div data-attr="insight-history-panel" className="insight-history-panel">
            <Tabs
                style={{
                    overflow: 'visible',
                }}
                animated={false}
                activeKey={activeTab}
                onChange={(activeKey: string): void => setActiveTab(activeKey)}
            >
                <TabPane
                    tab={<span data-attr="insight-history-tab">Recent</span>}
                    key={InsightHistoryType.RECENT}
                    data-attr="insight-history-pane"
                >
                    <InsightPane
                        data={insights.map((insight) => ({ ...insight }))}
                        loadMore={insightsNext ? loadNextInsights : undefined}
                        loadingMore={loadingMoreInsights}
                        footer={(item) => <>Ran query {dayjs(item.created_at).fromNow()}</>}
                        loading={insightsLoading}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Saved</span>}
                    key={InsightHistoryType.SAVED}
                    data-attr="insight-saved-pane"
                >
                    <InsightPane
                        data={savedInsights}
                        loadMore={savedInsightsNext ? loadNextSavedInsights : undefined}
                        loadingMore={loadingMoreSavedInsights}
                        footer={(item) => <>Saved {dayjs(item.created_at).fromNow()}</>}
                        loading={savedInsightsLoading}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Team</span>}
                    key={InsightHistoryType.TEAM}
                    data-attr="insight-team-panel"
                >
                    <InsightPane
                        data={teamInsights}
                        loadMore={teamInsightsNext ? loadNextTeamInsights : undefined}
                        loadingMore={loadingMoreTeamInsights}
                        footer={(item) => (
                            <>
                                Saved {dayjs(item.created_at).fromNow()} by{' '}
                                {item.created_by?.first_name || item.created_by?.email || 'unknown'}
                            </>
                        )}
                        loading={teamInsightsLoading}
                    />
                </TabPane>
            </Tabs>
        </div>
    )
}
