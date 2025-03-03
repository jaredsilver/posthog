import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { delay, idToKey, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { toast } from 'react-toastify'

export const dashboardsModel = kea({
    actions: () => ({
        delayedDeleteDashboard: (id) => ({ id }),
        setLastDashboardId: (id) => ({ id }),
        // this is moved out of dashboardLogic, so that you can click "undo" on a item move when already
        // on another dashboard - both dashboards can listen to and share this event, even if one is not yet mounted
        updateDashboardItem: (item) => ({ item }),
        pinDashboard: (id, source = null) => ({ id, source }),
        unpinDashboard: (id, source = null) => ({ id, source }),
    }),
    loaders: ({ values }) => ({
        rawDashboards: [
            {},
            {
                loadDashboards: async (shareToken = undefined, breakpoint) => {
                    await breakpoint(50)
                    try {
                        const { results } = await api.get(`api/dashboard?${toParams({ share_token: shareToken })}`)
                        return idToKey(results)
                    } catch {
                        return {}
                    }
                },
            },
        ],
        // We're not using this loader as a reducer per se, but just calling it `dashboard`
        // to have the right payload ({ dashboard }) in the Success actions
        dashboard: {
            addDashboard: async ({ name, show = false, useTemplate = '' }) => {
                const result = await api.create('api/dashboard', {
                    name,
                    pinned: true,
                    use_template: useTemplate,
                })
                if (show) {
                    router.actions.push(`/dashboard/${result.id}`)
                }
                return result
            },
            renameDashboard: async ({ id, name }, breakpoint) => {
                await breakpoint(700)
                const response = await api.update(`api/dashboard/${id}`, { name })
                eventUsageLogic.actions.reportDashboardRenamed(values.rawDashboards[id].name.length, name.length)
                return response
            },
            setIsSharedDashboard: async ({ id, isShared }) =>
                await api.update(`api/dashboard/${id}`, { is_shared: isShared }),
            deleteDashboard: async ({ id }) => await api.update(`api/dashboard/${id}`, { deleted: true }),
            restoreDashboard: async ({ id }) => await api.update(`api/dashboard/${id}`, { deleted: false }),
            pinDashboard: async ({ id, source }) => {
                const response = await api.update(`api/dashboard/${id}`, { pinned: true })
                eventUsageLogic.actions.reportDashboardPinToggled(true, source)
                return response
            },
            unpinDashboard: async ({ id, source }) => {
                const response = await api.update(`api/dashboard/${id}`, { pinned: false })
                eventUsageLogic.actions.reportDashboardPinToggled(false, source)
                return response
            },
        },
    }),

    reducers: () => ({
        redirect: [
            true,
            {
                deleteDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
                restoreDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
            },
        ],
        rawDashboards: {
            addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            restoreDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            renameDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            setIsSharedDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            deleteDashboardSuccess: (state, { dashboard }) => ({
                ...state,
                [dashboard.id]: { ...state[dashboard.id], deleted: true },
            }),
            delayedDeleteDashboard: (state, { id }) => {
                // this gives us time to leave the /dashboard/:deleted_id page
                const { [id]: _discard, ...rest } = state // eslint-disable-line
                return rest
            },
            pinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            unpinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
        },
        lastDashboardId: [
            null,
            { persist: true },
            {
                setLastDashboardId: (_, { id }) => id,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        dashboards: [
            () => [selectors.rawDashboards],
            (rawDashboards) => {
                const list = Object.values(rawDashboards).sort((a, b) =>
                    (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')
                )
                return [...list.filter((d) => d.pinned), ...list.filter((d) => !d.pinned)]
            },
        ],
        dashboardsLoading: [() => [selectors.rawDashboardsLoading], (rawDashboardsLoading) => rawDashboardsLoading],
        pinnedDashboards: [() => [selectors.dashboards], (dashboards) => dashboards.filter((d) => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),

    listeners: ({ actions, values }) => ({
        addDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" created!`)
        },

        restoreDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" restored!`)
            if (values.redirect) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },

        deleteDashboardSuccess: async ({ dashboard }) => {
            const toastId = toast(
                <span>
                    Dashboard "{dashboard.name}" deleted!{' '}
                    <a
                        href="#"
                        onClick={(e) => {
                            e.preventDefault()
                            actions.restoreDashboard({ id: dashboard.id, redirect: values.redirect })
                            toast.dismiss(toastId)
                        }}
                    >
                        Undo
                    </a>
                </span>
            )

            const { id } = dashboard
            const nextDashboard = [...values.pinnedDashboards, ...values.dashboards].find(
                (d) => d.id !== id && !d.deleted
            )

            if (values.redirect) {
                if (nextDashboard) {
                    router.actions.push(`/dashboard/${nextDashboard.id}`)
                } else {
                    router.actions.push('/dashboard')
                }

                await delay(500)
            }

            actions.delayedDeleteDashboard(id)
        },
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard/:id': ({ id }) => actions.setLastDashboardId(parseInt(id)),
    }),
})
