'use client'

import { useState } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import { toast } from '@/components/ui/toast'

export default function AuthPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const router = useRouter()

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)

    try {
      if (mode === 'signin') {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) throw error
      } else {
        const { error } = await supabase.auth.signUp({ email, password })
        if (error) throw error
      }
      router.push('/')
    } catch (error) {
      toast({
        title: "Authentication Error",
        description: error instanceof Error ? error.message : "Authentication failed",
        type: "error",
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-8 rounded-2xl border bg-card bg-linear-to-br from-primary/5 to-brand-pink/10 dark:from-primary/15 dark:to-brand-pink/10 p-8 shadow-sm">
        <div className="text-center space-y-2">
          <Image src="/logo.svg" alt="Voca" width={48} height={48} unoptimized className="mx-auto mb-4" />
          <h2 className="text-3xl font-bold tracking-tight">
            {mode === 'signin' ? 'Welcome Back' : 'Create Account'}
          </h2>
          <p className="text-sm text-muted-foreground">
            {mode === 'signin' ? 'Sign in to continue your practice' : 'Start your language journey today'}
          </p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleAuth}>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="email@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="rounded-lg"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="rounded-lg"
              />
            </div>
          </div>
          <Button className="w-full py-6 rounded-lg transition-all" type="submit" disabled={loading}>
            {loading ? 'Processing...' : mode === 'signin' ? 'Sign In' : 'Sign Up'}
          </Button>
        </form>
        <div className="text-center text-sm">
          {mode === 'signin' ? (
            <p className="text-muted-foreground">
              Don&apos;t have an account?{' '}
              <button 
                className="font-medium text-primary hover:underline" 
                onClick={() => setMode('signup')}
              >
                Sign up
              </button>
            </p>
          ) : (
            <p className="text-muted-foreground">
              Already have an account?{' '}
              <button 
                className="font-medium text-primary hover:underline" 
                onClick={() => setMode('signin')}
              >
                Sign in
              </button>
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
