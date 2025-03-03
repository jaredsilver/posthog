import React, { useState } from 'react'
import dayjs from 'dayjs'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin, Button, Input } from 'antd'
import { ExportOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions, kea } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { Cohort } from './Cohort'
import { Drawer } from 'lib/components/Drawer'
import { CohortType } from '~/types'
import api from 'lib/api'
import './cohorts.scss'
import Fuse from 'fuse.js'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'
import relativeTime from 'dayjs/plugin/relativeTime'
import { cohortsUrlLogicType } from './CohortsType'

dayjs.extend(relativeTime)

const cohortsUrlLogic = kea<cohortsUrlLogicType<CohortType>>({
    actions: {
        setOpenCohort: (cohort: CohortType | null) => ({ cohort }),
    },
    reducers: {
        openCohort: [
            null as null | CohortType,
            {
                setOpenCohort: (_, { cohort }) => cohort,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setOpenCohort: () => '/cohorts' + (values.openCohort ? '/' + (values.openCohort.id || 'new') : ''),
    }),
    urlToAction: ({ actions, values }) => ({
        '/cohorts(/:cohortId)': async ({ cohortId }: { cohortId: number | 'new' }) => {
            if (cohortId && cohortId !== 'new' && Number(cohortId) !== values.openCohort?.id) {
                const cohort = await api.get('api/cohort/' + cohortId)
                actions.setOpenCohort(cohort)
            }
        },
    }),
})

const searchCohorts = (sources: CohortType[], search: string): CohortType[] => {
    return new Fuse(sources, {
        keys: ['name'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export function Cohorts(): JSX.Element {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { loadCohorts } = useActions(cohortsModel)
    const { openCohort } = useValues(cohortsUrlLogic)
    const { setOpenCohort } = useActions(cohortsUrlLogic)
    const [searchTerm, setSearchTerm] = useState(false as string | false)

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            className: 'ph-no-capture',
            sorter: (a: CohortType, b: CohortType) => ('' + a.name).localeCompare(b.name as string),
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(_: any, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            sorter: (a: CohortType, b: CohortType) => (a.count || 0) - (b.count || 0),
        },
        createdAtColumn(),
        createdByColumn(cohorts),
        {
            title: (
                <span>
                    <Tooltip title="PostHog calculates what users belong to each cohort. This is then used when filtering on cohorts in the Trends page etc. Calculating happens every 15 minutes, or whenever a cohort is updated.">
                        Last calculation
                        <InfoCircleOutlined style={{ marginLeft: 6 }} />
                    </Tooltip>
                </span>
            ),
            render: function RenderCalculation(_: any, cohort: CohortType) {
                if (cohort.is_static) {
                    return <>N/A</>
                }
                return cohort.is_calculating ? (
                    <span>
                        Calculating <Spin />
                    </span>
                ) : (
                    dayjs(cohort.last_calculation).fromNow()
                )
            },
        },
        {
            title: 'Actions',
            render: function RenderActions(cohort: CohortType) {
                return (
                    <span>
                        <a href={'/api/person.csv?cohort=' + cohort.id}>
                            <Tooltip title="Export all users in this cohort as a .csv file">
                                <ExportOutlined />
                            </Tooltip>
                        </a>
                        {cohort.id !== 'new' && (
                            <DeleteWithUndo
                                endpoint="cohort"
                                object={{ name: cohort.name, id: cohort.id }}
                                className="text-danger"
                                style={{ marginLeft: 8 }}
                                callback={loadCohorts}
                            >
                                <DeleteOutlined />
                            </DeleteWithUndo>
                        )}
                    </span>
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader
                title="Cohorts"
                caption="Create lists of users who have something in common to use in analytics or feature flags."
            />
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
                <div className="mb float-right">
                    <Button
                        type="primary"
                        data-attr="create-cohort"
                        onClick={() => setOpenCohort({ id: 'new', groups: [{}] })}
                        icon={<PlusOutlined />}
                    >
                        New Cohort
                    </Button>
                </div>

                <Table
                    size="small"
                    columns={columns}
                    loading={cohortsLoading}
                    rowKey="id"
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    rowClassName="cursor-pointer"
                    onRow={(cohort) => ({
                        onClick: () => setOpenCohort(cohort),
                    })}
                    dataSource={searchTerm ? searchCohorts(cohorts, searchTerm) : cohorts}
                />
                <Drawer
                    title={openCohort?.id === 'new' ? 'New cohort' : openCohort?.name}
                    className="cohorts-drawer"
                    onClose={() => setOpenCohort(null)}
                    destroyOnClose={true}
                    visible={!!openCohort}
                >
                    {openCohort && <Cohort cohort={openCohort} />}
                </Drawer>
            </div>
        </div>
    )
}
