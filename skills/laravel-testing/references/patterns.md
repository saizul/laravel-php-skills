# Test patterns (Pest first, PHPUnit equivalent where it differs)

## Feature test skeleton

```php
// tests/Feature/PostControllerTest.php (Pest)
use App\Models\Post;
use App\Models\User;

beforeEach(function () {
    $this->user = User::factory()->create();
});

it('redirects guests to login', function () {
    $this->get(route('posts.create'))->assertRedirect(route('login'));
});

it('creates a post', function () {
    $this->actingAs($this->user)
        ->post(route('posts.store'), ['title' => 'Hello', 'body' => 'World'])
        ->assertRedirect()
        ->assertSessionHasNoErrors();

    $this->assertDatabaseHas('posts', ['title' => 'Hello', 'user_id' => $this->user->id]);
});

it('requires a title', function () {
    $this->actingAs($this->user)
        ->post(route('posts.store'), ['body' => 'x'])
        ->assertSessionHasErrors('title');
});

it('forbids updating another user\'s post', function () {
    $post = Post::factory()->create();   // belongs to someone else

    $this->actingAs($this->user)
        ->put(route('posts.update', $post), ['title' => 'Hacked'])
        ->assertForbidden();
});
```

PHPUnit:

```php
class PostControllerTest extends TestCase
{
    use RefreshDatabase;

    public function test_creates_a_post(): void
    {
        $user = User::factory()->create();

        $this->actingAs($user)->post(route('posts.store'), ['title' => 'Hello', 'body' => 'World'])
            ->assertRedirect();

        $this->assertDatabaseHas('posts', ['title' => 'Hello']);
    }
}
```

Datasets (Pest) for validation:

```php
it('validates input', function (array $data, string $field) {
    $this->actingAs(User::factory()->create())
        ->postJson('/api/posts', $data)
        ->assertUnprocessable()
        ->assertJsonValidationErrors($field);
})->with([
    'missing title' => [['body' => 'x'], 'title'],
    'long title'    => [['title' => str_repeat('a', 201), 'body' => 'x'], 'title'],
]);
```

## JSON APIs and Sanctum

```php
use Laravel\Sanctum\Sanctum;

it('lists my orders', function () {
    $user = User::factory()->hasOrders(3)->create();
    Order::factory()->count(2)->create();                 // other users' orders

    Sanctum::actingAs($user, ['orders:read']);

    $this->getJson('/api/orders')
        ->assertOk()
        ->assertJsonCount(3, 'data')
        ->assertJsonPath('data.0.user_id', $user->id)
        ->assertJsonStructure(['data' => [['id', 'total', 'status']], 'links', 'meta']);
});
```

## Fakes

| Boundary | Fake | Assert |
| --- | --- | --- |
| HTTP client | `Http::fake(['api.example.com/*' => Http::response([...], 200)])` | `Http::assertSent(fn ($r) => ...)`, `Http::assertNothingSent()` |
| Stray HTTP | `Http::preventStrayRequests()` | throws on unfaked requests |
| Queue | `Queue::fake()` | `Queue::assertPushed(Job::class, fn ($job) => ...)`, `assertPushedOn('emails', ...)` |
| Bus / batches | `Bus::fake()` | `Bus::assertDispatched`, `Bus::assertBatched` |
| Mail | `Mail::fake()` | `Mail::assertSent(Invoice::class, fn ($m) => $m->hasTo($user->email))`, `assertQueued` |
| Notifications | `Notification::fake()` | `Notification::assertSentTo($user, InvoicePaid::class)` |
| Events | `Event::fake([OrderShipped::class])` | `Event::assertDispatched(...)` (fake only what you assert) |
| Storage | `Storage::fake('s3')` | `Storage::disk('s3')->assertExists($path)` |
| Time | `$this->travel(3)->days()`, `$this->freezeTime()`, `Carbon::setTestNow('2026-01-01')` | |
| Sleep | `Sleep::fake()` (Laravel 10+) | `Sleep::assertSlept(...)` |
| Process | `Process::fake()` | `Process::assertRan('git pull')` |

`Event::fake()` without a list also stops model observers and Scout indexing; prefer a list.

## Files

```php
Storage::fake('public');
$file = UploadedFile::fake()->image('avatar.jpg', 200, 200)->size(500);   // KB

$this->actingAs($user)->post('/avatar', ['avatar' => $file])->assertRedirect();

Storage::disk('public')->assertExists('avatars/'.$file->hashName());
```

## Jobs, commands, policies

```php
it('marks the invoice paid', function () {
    $invoice = Invoice::factory()->unpaid()->create();
    Http::fake(['payments.example.com/*' => Http::response(['status' => 'paid'])]);

    (new SyncInvoice($invoice))->handle();

    expect($invoice->fresh()->paid_at)->not->toBeNull();
});

it('prunes old exports', function () {
    $this->artisan('exports:prune', ['--days' => 7])
        ->expectsOutputToContain('Deleted')
        ->assertExitCode(0);
});

it('lets only owners delete', function () {
    $post = Post::factory()->create();
    expect($post->user->can('delete', $post))->toBeTrue()
        ->and(User::factory()->create()->can('delete', $post))->toBeFalse();
});
```

## Exceptions

```php
it('rejects negative amounts', function () {
    app(ChargeCard::class)->handle(-5);
})->throws(InvalidArgumentException::class, 'Amount must be positive');

// Laravel 11+: assert reported exceptions without failing the request
Exceptions::fake();
$this->post('/webhook', [...])->assertOk();
Exceptions::assertReported(WebhookSignatureInvalid::class);
```

## Speed

- `DB_CONNECTION=sqlite`, `DB_DATABASE=:memory:` in `phpunit.xml` when the schema allows.
- `BCRYPT_ROUNDS=4` (Laravel default in `phpunit.xml`), `CACHE_STORE=array`, `QUEUE_CONNECTION=sync`,
  `MAIL_MAILER=array`, `SESSION_DRIVER=array`.
- `php artisan test --parallel` (each process gets its own database).
- `LazilyRefreshDatabase` skips migrations for tests that never touch the DB.
- Find slow tests: `./vendor/bin/pest --profile` or `php artisan test --profile`.

## Architecture tests (Pest 3)

```php
arch()->preset()->laravel();
arch('no debugging calls')->expect(['dd', 'dump', 'ray'])->not->toBeUsed();
arch('models extend Model')->expect('App\Models')->toExtend('Illuminate\Database\Eloquent\Model');
```
