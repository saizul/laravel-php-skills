<?php

use App\Models\Post;
use App\Models\User;
use Illuminate\Support\Facades\Http;

it('shows a post', function () {
    $post = Post::factory()->create();

    $this->get('/posts/1')->assertOk();
})->only();

it('syncs to the crm', function () {
    $response = Http::post('https://crm.example.com/api/contacts', ['name' => 'x']);
    sleep(2);
    dd($response->json());
});

test('creates a post', function () {
    $user = User::factory()->create();
    $this->actingAs($user)->withoutMiddleware()->post('/posts', ['title' => 'Hi']);
});

it('is pending')->todo();

it('throws on bad input', function () {
    app(\App\Actions\CreatePost::class)->handle([]);
})->throws(InvalidArgumentException::class);

it('uses an arrow function', fn () => expect(true)->toBeTrue());
