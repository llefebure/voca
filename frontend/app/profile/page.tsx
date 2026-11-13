'use client'

import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useRouter } from 'next/navigation'
import { Target, Settings, BookOpen, Save, X, TrendingUp } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'
import { toast } from '@/components/ui/toast'
import {
  SUPPORTED_LANGUAGES,
  UPCOMING_LANGUAGES,
  languageName,
} from '@/lib/languages'

type ProfileFields = {
  target_language?: string
  level?: string
  goals?: string
  interests?: string
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<ProfileFields | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editedProfile, setEditedProfile] = useState<ProfileFields>({})
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/auth')
          return
        }

        const { data } = await supabase
          .from('profiles')
          .select('*')
          .eq('id', user.id)
          .single()

        setProfile(data)
        setEditedProfile(data)
      } catch (error) {
        console.error('Error fetching profile:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchProfile()
  }, [router])

  const handleSave = async () => {
    try {
      const { data: { user } } = await supabase.auth.getUser()
      await supabase.from('profiles').update(editedProfile).eq('id', user?.id)
      setProfile(editedProfile)
      setIsEditing(false)
      toast({
        title: "Profile Updated",
        description: "Your learning profile has been saved.",
        type: "success",
      })
    } catch {
      toast({
        title: "Save Failed",
        description: "Could not save your profile changes.",
        type: "error",
      })
    }
  }

  if (loading) return (
    <DashboardLayout title="Profile">
      <div className="flex h-full items-center justify-center text-muted-foreground">Loading profile...</div>
    </DashboardLayout>
  )

  return (
    <DashboardLayout title="My Profile">
      <div className="mx-auto max-w-4xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Title is in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Return to Chat
          </Button>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          <Card className="md:col-span-1 border-t-4 border-t-primary">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Settings className="h-5 w-5 text-muted-foreground" />
                Account
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Learning</Label>
                <p className="text-2xl font-bold">{languageName(profile?.target_language)}</p>
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Current Level</Label>
                <p className="text-2xl font-bold">{profile?.level || 'Not set'}</p>
              </div>
              <Button 
                className="w-full rounded-lg" 
                variant={isEditing ? 'outline' : 'default'} 
                onClick={() => setIsEditing(!isEditing)}
              >
                {isEditing ? (
                  <span className="flex items-center gap-2"><X className="h-4 w-4" /> Cancel</span>
                ) : (
                  'Edit Profile'
                )}
              </Button>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Target className="h-5 w-5 text-muted-foreground" />
                Learning Goals & Interests
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isEditing ? (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Learning language</Label>
                    <div className="grid grid-cols-2 gap-2">
                      {SUPPORTED_LANGUAGES.map((lang) => (
                        <Button
                          key={lang.code}
                          variant={editedProfile.target_language === lang.code ? 'default' : 'outline'}
                          onClick={() => setEditedProfile({...editedProfile, target_language: lang.code})}
                        >
                          {lang.name}
                        </Button>
                      ))}
                      {UPCOMING_LANGUAGES.map((name) => (
                        <Button key={name} variant="outline" disabled>
                          {name}
                          <span className="ml-1 text-xs text-muted-foreground">Soon</span>
                        </Button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>Goals</Label>
                    <Input 
                      value={editedProfile.goals} 
                      onChange={(e) => setEditedProfile({...editedProfile, goals: e.target.value})} 
                      className="rounded-lg"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Interests</Label>
                    <Input 
                      value={editedProfile.interests} 
                      onChange={(e) => setEditedProfile({...editedProfile, interests: e.target.value})} 
                      className="rounded-lg"
                    />
                  </div>
                  <Button className="w-full rounded-lg flex items-center gap-2" onClick={handleSave}>
                    <Save className="h-4 w-4" /> Save Changes
                  </Button>
                </div>
              ) : (
                <div className="grid gap-6">
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">My Goals</p>
                    <p className="text-foreground leading-relaxed">{profile?.goals || 'No goals set yet.'}</p>
                  </div>
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Interests</p>
                    <p className="text-foreground leading-relaxed">{profile?.interests || 'No interests set yet.'}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Card className="border-t-4 border-t-primary/30">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-muted-foreground" />
              SRS Progress
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-12 text-center space-y-3">
              <div className="bg-muted p-4 rounded-full">
                <TrendingUp className="h-8 w-8 text-muted-foreground" />
              </div>
              <p className="text-muted-foreground italic">
                Your spaced repetition progress will be visualized here.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  )
}
