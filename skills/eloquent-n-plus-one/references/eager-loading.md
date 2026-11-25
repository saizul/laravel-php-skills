# Eager loading reference

## The N+1 shape

```php
$posts = Post::latest()->paginate(15);   // 1 query
foreach ($posts as $post) {
    echo $post->user->name;              // +15 queries: select * from users where id = ?
    echo $post->comments()->count();     // +15 queries: select count(*) ... where post_id = ?
}
```

Fixed: 3 queries regardless of page size.

```php
$posts = Post::with('user:id,name')->withCount('comments')->latest()->paginate(15);
foreach ($posts as $post) {
    echo $post->user->name;
    echo $post->comments_count;
}
```

Note `$post->comments()->count()` (method call) always queries, even after `withCount`.
Use the `comments_count` attribute.

## Fix catalogue

| Need | Code |
| --- | --- |
| belongsTo / hasOne / hasMany | `->with('user')`, `->with(['user', 'tags'])` |
| nested | `->with('comments.author')` |
| constrained | `->with(['comments' => fn ($q) => $q->latest()->limit(5)])` (per-parent limit needs Laravel 11+ or a package) |
| selected columns | `->with('user:id,name')` (include the foreign/primary key) |
| counts | `->withCount('comments')`, `->withCount(['comments as approved_count' => fn ($q) => $q->where('approved', true)])` |
| exists | `->withExists('subscription')` -> `subscription_exists` |
| sums / averages | `->withSum('items', 'price')` -> `items_sum_price`, `withAvg`, `withMax`, `withMin` |
| polymorphic | `->with('commentable')` + `MorphTo::morphWith([Post::class => ['author']])` |
| already have the collection | `$posts->load('user')`, `$posts->loadMissing('user')`, `$posts->loadCount('comments')` |
| always needed | `protected $with = ['user'];` on the model (use sparingly: it applies everywhere) |
| latest child only | `hasOne(...)->latestOfMany()` then `->with('latestComment')` |

## Where N+1 hides

- **Blade loops and components** receiving models.
- **API Resources**: `'author' => $this->user->name`. Use
  `'author' => new UserResource($this->whenLoaded('user'))` and eager load in the controller.
- **Accessors / `$appends`**: an accessor that reads a relation runs for every serialized model.
- **Policies** in `@can` inside loops that read relations (`$post->team->owner_id`).
- **Livewire**: models in public properties are rehydrated each request; relations are lost
  unless eager loaded in `mount()`/`render()`.
- **Queued jobs and commands** looping over `Model::all()`: use `chunkById()` + `with()`.
- **Observers / events** that load relations on every save.

## Guard rails

```php
// app/Providers/AppServiceProvider.php
use Illuminate\Database\Eloquent\Model;

public function boot(): void
{
    Model::preventLazyLoading(! $this->app->isProduction());
    // Or in production, log instead of throwing:
    Model::handleLazyLoadingViolationUsing(function ($model, $relation) {
        logger()->warning('Attempted to lazy load ['.$relation.'] on model ['.get_class($model).'] but lazy loading is disabled.');
    });
}
```

The log message format above matches what `find_n_plus_one.py` parses.

### Query-count test (PHPUnit or Pest)

```php
use Illuminate\Support\Facades\DB;

it('lists posts with a constant number of queries', function () {
    Post::factory()->count(20)->for(User::factory())->hasComments(3)->create();

    DB::enableQueryLog();
    $this->get('/posts')->assertOk();

    expect(count(DB::getQueryLog()))->toBeLessThanOrEqual(5);
});
```

Seed more rows than the page size so a regression shows up as a big jump, not +1.

## Laravel Debugbar and Telescope

- Debugbar's "Queries" tab marks duplicates; its "Models" tab shows hydrated model counts.
- Telescope groups all queries of a request under one `batch_id`; the script uses it.
- Both are development tools: never enable them on a public production site without a gate.
