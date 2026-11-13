'use client'

import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useRouter } from 'next/navigation'
import { Calendar, ArrowRight, Clock, FileText, MessageSquare } from 'lucide-react'
import { format } from 'date-fns'
import { DashboardLayout } from '@/components/dashboard-layout'
import { useLanguage } from '@/components/language-context'
import { cn } from '@/lib/utils'

type SessionRow = {
  session_id: string
  status: string
  created_at?: string | null
  end_time?: string | null
  recap?: Record<string, unknown> | null
}

export default function HistoryPage() {
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [loading, setLoading] = useState(true)
  const router = useRouter()
  // History shows the active learning language's sessions (context from the sidebar
  // toggle); the backend falls back to everything when the param is absent.
  const { activeLanguage, loading: languageLoading } = useLanguage()

  useEffect(() => {
    if (languageLoading || !activeLanguage) return
    const fetchSessions = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) {
          router.push('/auth')
          return
        }

        const response = await fetch(
          `http://localhost:8000/sessions?language=${encodeURIComponent(activeLanguage)}`,
          {
            headers: {
              'Authorization': `Bearer ${session.access_token}`
            }
          }
        )
        
        if (!response.ok) throw new Error('Failed to fetch sessions')
        const data = await response.json()
        setSessions(data.sessions || [])
      } catch (error) {
        console.error('Error fetching sessions:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchSessions()
  }, [router, activeLanguage, languageLoading])

  return (
    <DashboardLayout title="Session History">
      <div className="mx-auto max-w-5xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Title is already in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Start New Session
          </Button>
        </div>

        {loading ? (
          <div className="flex h-64 items-center justify-center text-muted-foreground">Loading your history...</div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-20 space-y-4">
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
              <Clock className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium">No sessions yet</h3>
            <p className="text-muted-foreground">Your past conversations will appear here.</p>
          </div>
        ) : (
          <div className="rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[250px]">Date</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow key={session.session_id} className="group">
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Calendar className="h-4 w-4 text-muted-foreground" />
                        {session.created_at ? format(new Date(session.created_at), 'PPP p') : 'Unknown date'}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className={cn(
                        "px-2 py-1 rounded-full text-xs font-medium",
                        session.status === 'completed' 
                          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" 
                          : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                      )}>
                        {session.status === 'completed' ? 'Completed' : 'Active'}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        {session.status === 'active' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="flex items-center gap-2 text-muted-foreground hover:bg-primary hover:text-primary-foreground"
                            onClick={() => router.push(`/?session=${session.session_id}`)}
                          >
                            Continue <MessageSquare className="h-3 w-3" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="flex items-center gap-2 text-muted-foreground hover:bg-primary hover:text-primary-foreground"
                          onClick={() => router.push(`/history/${session.session_id}`)}
                        >
                          View Transcript <FileText className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={!session.recap}
                          className="flex items-center gap-2 text-primary hover:text-primary-foreground hover:bg-primary"
                          onClick={() => router.push(`/recap/${session.session_id}`)}
                        >
                          View Recap
                          <ArrowRight className="h-3 w-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </DashboardLayout>
  )
}
