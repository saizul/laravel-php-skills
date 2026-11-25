<?php

use App\Models\Post;
use App\Models\User;
use Illuminate\Support\Facades\Http;

it('shows a post', function () {
    $post = Post::factory()->create();

    $this->get("/posts/{$post->id}")->assertOk()->assertSee($post->title);
});

it('syncs to the crm', function () {
    Http::fake(['crm.example.com/*' => Http::response(['id' => 1], 201)]);

    app(\App\Services\Crm::class)->push(User::factory()->create());

    Http::assertSent(fn ($request) => $request->url() === 'https://crm.example.com/api/contacts');
});

it('expires links after a day', function () {
    $this->travel(25)->hours();
    $this->get(route('dashboard'))->assertRedirect('/login');
});

it('rejects bad input', function () {
    app(\App\Actions\CreatePost::class)->handle([]);
})->throws(InvalidArgumentException::class);
