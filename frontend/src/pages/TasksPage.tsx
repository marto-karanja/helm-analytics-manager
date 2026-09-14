import * as React from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { api } from '@/lib/api'
import type { Task } from '@/lib/types'

type TaskWithProject = Task & { project_name: string; project_slug: string }

const PRIORITY_VARIANT: Record<string, 'red' | 'yellow' | 'muted'> = {
  high: 'red',
  normal: 'yellow',
  low: 'muted',
}

export function TasksPage() {
  const [tasks, setTasks] = React.useState<TaskWithProject[] | null>(null)

  React.useEffect(() => {
    api.get<TaskWithProject[]>('/tasks').then((resp) => setTasks(resp.data))
  }, [])

  if (!tasks) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (tasks.length === 0) return <p className="text-sm text-muted-foreground">Nothing open across any project.</p>

  return (
    <div className="flex flex-col gap-2">
      <h1 className="mb-2 text-xl font-semibold">What needs attention</h1>
      {tasks.map((task) => (
        <Card key={task.id}>
          <CardContent className="flex items-center justify-between gap-4 py-3">
            <div>
              <p className="text-sm font-medium">{task.title}</p>
              <Link to={`/projects/${task.project_id}`} className="text-xs text-muted-foreground hover:underline">
                {task.project_name}
              </Link>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={PRIORITY_VARIANT[task.priority] ?? 'muted'}>{task.priority}</Badge>
              <Badge variant="outline">{task.status.replace('_', ' ')}</Badge>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
