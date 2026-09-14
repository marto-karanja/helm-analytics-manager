import * as React from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { createTask, updateTask } from '@/lib/api'
import type { Task } from '@/lib/types'

const COLUMNS: { status: Task['status']; label: string }[] = [
  { status: 'todo', label: 'Todo' },
  { status: 'in_progress', label: 'In Progress' },
  { status: 'done', label: 'Done' },
]

export function TaskBoard({
  projectId,
  tasks,
  onChange,
  readOnly = false,
}: {
  projectId: string
  tasks: Task[]
  onChange: (tasks: Task[]) => void
  readOnly?: boolean
}) {
  const [newTitle, setNewTitle] = React.useState('')
  const [adding, setAdding] = React.useState(false)

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!newTitle.trim()) return
    setAdding(true)
    try {
      const task = await createTask(projectId, newTitle.trim())
      onChange([...tasks, task])
      setNewTitle('')
    } finally {
      setAdding(false)
    }
  }

  async function moveTask(task: Task, status: Task['status']) {
    const updated = await updateTask(task.id, { status })
    onChange(tasks.map((t) => (t.id === task.id ? updated : t)))
  }

  return (
    <div className="flex flex-col gap-4">
      {!readOnly && (
        <form className="flex gap-2" onSubmit={handleAdd}>
          <Input
            placeholder="New task…"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <Button type="submit" disabled={adding}>
            Add
          </Button>
        </form>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {COLUMNS.map((col) => (
          <Card key={col.status}>
            <CardHeader>
              <CardTitle className="text-sm text-muted-foreground">{col.label}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {tasks
                .filter((t) => t.status === col.status)
                .map((task) => (
                  <div key={task.id} className="rounded-md border border-border p-2 text-sm">
                    <p>{task.title}</p>
                    {!readOnly && (
                      <div className="mt-2 flex gap-1">
                        {COLUMNS.filter((c) => c.status !== task.status).map((c) => (
                          <Button
                            key={c.status}
                            variant="outline"
                            size="sm"
                            onClick={() => moveTask(task, c.status)}
                          >
                            → {c.label}
                          </Button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              {tasks.filter((t) => t.status === col.status).length === 0 && (
                <p className="text-xs text-muted-foreground">No tasks.</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
